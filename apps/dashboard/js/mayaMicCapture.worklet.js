/**
 * Maya mic capture AudioWorklet (AUDIO-006).
 * Converts mono float input to PCM16 chunks off the main thread.
 */
class MayaMicCaptureProcessor extends AudioWorkletProcessor {
  constructor(options) {
    super();
    const opts = (options && options.processorOptions) || {};
    this._chunkSize = Math.max(128, (opts.chunkSize | 0) || 2048);
    this._gain = typeof opts.gain === "number" ? opts.gain : 1;
    this._pending = new Float32Array(this._chunkSize);
    this._filled = 0;
    this._sampleIndex = 0;
    this.port.onmessage = (ev) => {
      const data = ev.data || {};
      if (data.type === "gain" && typeof data.value === "number") {
        this._gain = data.value;
      } else if (data.type === "reset") {
        this._filled = 0;
        this._sampleIndex = 0;
      }
    };
  }

  _flush() {
    const n = this._chunkSize;
    const pcm = new Int16Array(n);
    const g = this._gain || 1;
    const src = this._pending;
    for (let i = 0; i < n; i++) {
      const sample = Math.max(-1, Math.min(1, src[i] * g));
      pcm[i] = sample < 0 ? sample * 32768 : sample * 32767;
    }
    const sampleIndex = this._sampleIndex >>> 0;
    this._sampleIndex = (this._sampleIndex + n) >>> 0;
    this._filled = 0;
    // Transfer the underlying buffer to avoid structured-clone copies.
    this.port.postMessage(
      { type: "pcm", sampleIndex: sampleIndex, samples: n, buffer: pcm.buffer },
      [pcm.buffer],
    );
  }

  process(inputs) {
    const input = inputs[0] && inputs[0][0];
    if (!input || input.length === 0) {
      return true;
    }
    let offset = 0;
    while (offset < input.length) {
      const space = this._chunkSize - this._filled;
      const take = Math.min(space, input.length - offset);
      this._pending.set(input.subarray(offset, offset + take), this._filled);
      this._filled += take;
      offset += take;
      if (this._filled >= this._chunkSize) {
        this._flush();
      }
    }
    return true;
  }
}

registerProcessor("maya-mic-capture", MayaMicCaptureProcessor);
