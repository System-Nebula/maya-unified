const state = {
  ws: null,
  stream: null,
  context: null,
  source: null,
  processor: null,
  activeGeneration: null,
  audioQueue: [],
  scheduledSources: new Set(),
  playbackCursor: 0,
  scheduling: false,
  playing: false,
  playbackGain: null,
};

const statusEl = document.querySelector("#status");
const startButton = document.querySelector("#start");
const interruptButton = document.querySelector("#interrupt");
const transcript = document.querySelector("#transcript");
const meterFill = document.querySelector("#meter-fill");
const gainSlider = document.querySelector("#gain");
const telemetry = document.querySelector("#telemetry");
const voiceForm = document.querySelector("#voice-form");
const voiceStatus = document.querySelector("#voice-status");
const micDevice = document.querySelector("#mic-device");
let latestAsrMs = null;
let firstAudioMs = null;

function setStatus(text) { statusEl.textContent = text; }

function addMessage(role, text, id = null) {
  let row = id ? document.querySelector(`[data-message-id="${id}"]`) : null;
  if (!row) {
    row = document.createElement("div");
    row.className = `message ${role}`;
    if (id) row.dataset.messageId = id;
    row.innerHTML = `<span class="role">${role.toUpperCase()}</span><span class="content"></span>`;
    transcript.appendChild(row);
  }
  row.querySelector(".content").textContent += text;
  transcript.scrollTop = transcript.scrollHeight;
}

function connect() {
  if (state.ws && state.ws.readyState <= 1) return;
  const protocol = location.protocol === "https:" ? "wss" : "ws";
  state.ws = new WebSocket(`${protocol}://${location.host}/ws/duplex`);
  state.ws.binaryType = "arraybuffer";
  state.ws.onopen = () => setStatus("Connected");
  state.ws.onclose = () => setStatus("Disconnected");
  state.ws.onerror = () => setStatus("Connection error");
  state.ws.onmessage = event => {
    const data = JSON.parse(event.data);
    if (data.type === "ready") {
      state.activeGeneration = data.generation_id;
      setStatus("Listening");
    } else if (data.type === "transcribing") {
      setStatus("Transcribing");
    } else if (data.type === "timing") {
      latestAsrMs = data.asr_ms;
      telemetry.textContent = `ASR ${data.asr_ms} ms`;
    } else if (data.type === "user_text") {
      addMessage("user", data.text);
    } else if (data.type === "assistant_start") {
      state.activeGeneration = data.generation_id;
      addMessage("assistant", "", data.generation_id);
      firstAudioMs = null;
      setStatus("Thinking");
    } else if (data.type === "delivery" && data.generation_id === state.activeGeneration) {
      telemetry.dataset.delivery = data.instruct;
    } else if (data.type === "assistant_text_delta" && data.generation_id === state.activeGeneration) {
      addMessage("assistant", data.text, data.generation_id);
    } else if (data.type === "audio" && data.generation_id === state.activeGeneration) {
      if (data.response_audio_chunk === 1) firstAudioMs = data.total_ms;
      telemetry.textContent = `ASR ${latestAsrMs ?? "typed"} | LLM ${data.llm_first_token_ms} ms | TTS ${data.tts_ms} ms | first audio ${firstAudioMs ?? "…"} ms`;
      state.audioQueue.push(data);
      scheduleAudio();
    } else if (data.type === "duck_audio") {
      setPlaybackGain(0.22, 0.06);
      setStatus("Listening while speaking");
    } else if (data.type === "resume_audio") {
      setPlaybackGain(1, 0.12);
      setStatus("Speaking");
    } else if (data.type === "backchannel") {
      console.info("Backchannel ignored", data.text);
    } else if (data.type === "clear_audio") {
      state.activeGeneration = data.generation_id;
      clearAudio();
      setStatus("Listening");
    } else if (data.type === "assistant_end" && !state.playing) {
      setStatus("Listening");
    } else if (data.type === "error") {
      setStatus("Error");
      addMessage("assistant", `[${data.message}]`);
    }
  };
}

function floatToPCM16(float32, gain = 1) {
  const out = new Int16Array(float32.length);
  for (let i = 0; i < float32.length; i++) {
    const sample = Math.max(-1, Math.min(1, float32[i] * gain));
    out[i] = sample < 0 ? sample * 32768 : sample * 32767;
  }
  return out;
}

async function ensureAudioContext() {
  if (!state.context) state.context = new AudioContext({ sampleRate: 48000, latencyHint: "interactive" });
  if (!state.playbackGain) {
    state.playbackGain = state.context.createGain();
    state.playbackGain.connect(state.context.destination);
  }
  if (state.context.state === "suspended") await state.context.resume();
  return state.context;
}

async function startMicrophone() {
  connect();
  const context = await ensureAudioContext();
  const deviceId = micDevice.value || undefined;
  state.stream = await navigator.mediaDevices.getUserMedia({
    audio: {
      deviceId: deviceId ? { exact: deviceId } : undefined,
      channelCount: 1,
      sampleRate: 48000,
      echoCancellation: true,
      noiseSuppression: true,
      autoGainControl: true,
    },
  });
  state.source = context.createMediaStreamSource(state.stream);
  state.processor = context.createScriptProcessor(2048, 1, 1);
  state.source.connect(state.processor);
  state.processor.connect(context.destination);
  state.processor.onaudioprocess = event => {
    if (!state.ws || state.ws.readyState !== WebSocket.OPEN) return;
    const input = event.inputBuffer.getChannelData(0);
    let energy = 0;
    for (const sample of input) energy += sample * sample;
    meterFill.style.width = `${Math.min(100, Math.sqrt(energy / input.length) * 600)}%`;
    state.ws.send(floatToPCM16(input, Number(gainSlider.value)).buffer);
  };
  startButton.textContent = "Microphone active";
  startButton.disabled = true;
  setStatus("Listening");
}

function base64Bytes(value) {
  const binary = atob(value);
  const bytes = new Uint8Array(binary.length);
  for (let i = 0; i < binary.length; i++) bytes[i] = binary.charCodeAt(i);
  return bytes.buffer;
}

function setPlaybackGain(value, seconds = 0.05) {
  if (!state.context || !state.playbackGain) return;
  const now = state.context.currentTime;
  state.playbackGain.gain.cancelScheduledValues(now);
  state.playbackGain.gain.setValueAtTime(state.playbackGain.gain.value, now);
  state.playbackGain.gain.linearRampToValueAtTime(value, now + seconds);
}

function reportPlayback(speaking) {
  if (state.ws?.readyState === WebSocket.OPEN) {
    state.ws.send(JSON.stringify({ type: "playback_state", speaking }));
  }
}

async function scheduleAudio() {
  if (state.scheduling) return;
  state.scheduling = true;
  try {
    const context = await ensureAudioContext();
    while (state.audioQueue.length) {
      const item = state.audioQueue.shift();
      if (item.generation_id !== state.activeGeneration) continue;
      const buffer = await context.decodeAudioData(base64Bytes(item.data));
      if (item.generation_id !== state.activeGeneration) continue;
      const source = context.createBufferSource();
      source.buffer = buffer;
      source.connect(state.playbackGain);
      const startAt = Math.max(state.playbackCursor, context.currentTime + (state.playing ? 0.01 : 0.30));
      state.playbackCursor = startAt + buffer.duration;
      state.scheduledSources.add(source);
      if (!state.playing) {
        state.playing = true;
        reportPlayback(true);
        setStatus("Speaking");
      }
      source.onended = () => {
        state.scheduledSources.delete(source);
        if (!state.scheduledSources.size && !state.audioQueue.length && !state.scheduling) {
          state.playing = false;
          state.playbackCursor = 0;
          reportPlayback(false);
          setStatus("Listening");
        }
      };
      source.start(startAt);
    }
  } catch (error) {
    console.error("audio scheduling failed", error);
    setStatus(`Playback failed: ${error.message}`);
  } finally {
    state.scheduling = false;
  }
}

function clearAudio() {
  state.audioQueue = [];
  for (const source of state.scheduledSources) {
    try { source.stop(); } catch (_) {}
  }
  state.scheduledSources.clear();
  state.playbackCursor = 0;
  state.playing = false;
  reportPlayback(false);
}

function interrupt() {
  clearAudio();
  if (state.ws?.readyState === WebSocket.OPEN) state.ws.send(JSON.stringify({ type: "interrupt" }));
}

startButton.addEventListener("click", () => startMicrophone().catch(error => setStatus(`Microphone failed: ${error.message}`)));
interruptButton.addEventListener("click", interrupt);

document.querySelector("#text-form").addEventListener("submit", event => {
  event.preventDefault();
  const input = document.querySelector("#text-input");
  const text = input.value.trim();
  if (!text) return;
  ensureAudioContext();
  connect();
  const send = () => { state.ws.send(JSON.stringify({ type: "text", text })); input.value = ""; };
  if (state.ws.readyState === WebSocket.OPEN) send();
  else state.ws.addEventListener("open", send, { once: true });
});

voiceForm.addEventListener("submit", async event => {
  event.preventDefault();
  const button = voiceForm.querySelector("button");
  button.disabled = true;
  voiceStatus.textContent = "Loading clone model and warming the voice…";
  try {
    const response = await fetch("/api/duplex/voice/clone", { method: "POST", body: new FormData(voiceForm) });
    const payload = await response.json();
    if (!response.ok) throw new Error(payload.detail || "Voice upload failed");
    voiceForm.querySelector("textarea[name=transcript]").value = payload.transcript;
    voiceStatus.textContent = `Ready: ${payload.voice.speaker} — transcript generated`;
  } catch (error) {
    voiceStatus.textContent = `Error: ${error.message}`;
  } finally {
    button.disabled = false;
  }
});

fetch("/api/duplex/config").then(r => r.json()).then(c => {
  voiceStatus.textContent = `${c.voice.mode}: ${c.voice.speaker} | HushMic ${c.hushmic.ready ? "on" : "off"}`;
});
async function refreshMicrophones() {
  try {
    await navigator.mediaDevices.getUserMedia({ audio: true }).then(s => s.getTracks().forEach(t => t.stop()));
    const devices = (await navigator.mediaDevices.enumerateDevices()).filter(d => d.kind === "audioinput");
    micDevice.innerHTML = '<option value="">System default</option>';
    for (const device of devices) {
      const option = document.createElement("option");
      option.value = device.deviceId;
      option.textContent = device.label || `Microphone ${micDevice.options.length}`;
      if (/hushmic/i.test(device.label)) option.selected = true;
      micDevice.appendChild(option);
    }
  } catch (error) {
    console.warn("Could not enumerate microphones", error);
  }
}
refreshMicrophones();
