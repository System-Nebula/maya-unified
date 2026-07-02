/** WebLLM bridge — runs @mlc-ai/web-llm in-browser for server voice + chat turns. */
(function () {
  // Use the published browser bundle directly — esm.sh re-bundles and breaks with createRequire.
  const WEBLLM_SOURCES = [
    "https://cdn.jsdelivr.net/npm/@mlc-ai/web-llm@0.2.80/lib/index.js",
    "https://esm.run/@mlc-ai/web-llm@0.2.80",
  ];

  const state = {
    engine: null,
    modelId: null,
    status: "idle",
    ready: false,
    loading: false,
    loadGen: 0,
    unsub: null,
    unloadSub: null,
    _pagehideBound: false,
    gpuLabel: "",
    gpuIssue: "",
  };

  let unloadPromise = null;

  const TROUBLESHOOT =
    "Edge is in software rendering mode. Fix: edge://settings/system → turn ON graphics acceleration, " +
    "edge://flags → enable ignore-gpu-blocklist, Windows Settings → Graphics → Edge → High performance (RTX 5090), " +
    "then fully quit and reopen Edge. Check edge://gpu shows WebGPU: Hardware accelerated.";

  async function postReady(ready) {
    try {
      await fetch("/api/voice/agent/webllm/ready", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ ready: !!ready }),
      });
    } catch (_) {}
  }

  async function fulfill(id, payload) {
    await fetch("/api/voice/agent/webllm/fulfill", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ id, ...payload }),
    });
  }

  async function adapterLabel(adapter) {
    try {
      if (adapter?.requestAdapterInfo) {
        const info = await adapter.requestAdapterInfo();
        return info.device || info.description || info.vendor || "GPU";
      }
    } catch (_) {}
    return "GPU";
  }

  async function probeMainThread() {
    if (!navigator.gpu) {
      return { ok: false, where: "main", reason: "WebGPU API missing — use Chrome/Edge 113+" };
    }
    const attempts = [
      { powerPreference: "high-performance" },
      { powerPreference: "low-power" },
      {},
    ];
    for (const opts of attempts) {
      try {
        const adapter = await navigator.gpu.requestAdapter(opts);
        if (adapter) {
          const label = await adapterLabel(adapter);
          if (/basic render|swiftshader|warp|software/i.test(label)) {
            return {
              ok: false,
              where: "main",
              reason: `Browser is using software GPU (${label}), not your RTX 5090`,
            };
          }
          return { ok: true, where: "main", label };
        }
      } catch (_) {}
    }
    return {
      ok: false,
      where: "main",
      reason:
        "requestAdapter returned null — Edge is in software mode and WebGPU is blocklisted",
    };
  }

  function probeWorkerThread() {
    const src = `
      self.onmessage = async () => {
        try {
          if (!self.navigator?.gpu) {
            self.postMessage({ ok: false, reason: "WebGPU missing in worker" });
            return;
          }
          const opts = [{ powerPreference: "high-performance" }, {}];
          for (const o of opts) {
            const adapter = await self.navigator.gpu.requestAdapter(o);
            if (adapter) {
              self.postMessage({ ok: true });
              return;
            }
          }
          self.postMessage({ ok: false, reason: "requestAdapter null in worker" });
        } catch (e) {
          self.postMessage({ ok: false, reason: e.message || String(e) });
        }
      };
    `;
    const blob = new Blob([src], { type: "application/javascript" });
    const url = URL.createObjectURL(blob);
    const worker = new Worker(url);
    return new Promise((resolve) => {
      const done = (result) => {
        URL.revokeObjectURL(url);
        worker.terminate();
        resolve(result);
      };
      worker.onmessage = (e) => done({ ok: !!e.data?.ok, where: "worker", reason: e.data?.reason || "" });
      worker.onerror = (e) => done({ ok: false, where: "worker", reason: e.message || "worker error" });
      worker.postMessage(null);
    });
  }

  async function diagnoseWebGPU() {
    const main = await probeMainThread();
    if (!main.ok) {
      state.gpuIssue = `${main.reason}. ${TROUBLESHOOT}`;
      return main;
    }
    state.gpuLabel = main.label || "GPU";
    const worker = await probeWorkerThread();
    if (!worker.ok) {
      state.gpuIssue =
        `Main thread sees ${state.gpuLabel}, but WebGPU failed inside a worker (${worker.reason}). ` +
        "Update Chrome/Edge, enable chrome://flags/#ignore-gpu-blocklist, then hard-refresh.";
      return worker;
    }
    state.gpuIssue = "";
    return { ok: true, label: state.gpuLabel };
  }

  async function loadWebLLM() {
    let lastErr = null;
    for (const url of WEBLLM_SOURCES) {
      try {
        const mod = await import(url);
        if (mod?.CreateMLCEngine) return mod;
        if (mod?.default?.CreateMLCEngine) return mod.default;
        throw new Error("CreateMLCEngine export missing");
      } catch (e) {
        lastErr = e;
        console.warn("[mayaWebLLM] failed to load from", url, e);
      }
    }
    throw lastErr || new Error("Could not load WebLLM");
  }

  async function disposeEngine(engine) {
    if (!engine || typeof engine.unload !== "function") return;
    try {
      await engine.unload();
      console.info("[mayaWebLLM] engine.unload() finished — GPU weights released in browser");
    } catch (e) {
      console.warn("[mayaWebLLM] engine.unload failed:", e);
    }
  }

  async function ensureEngine(modelId) {
    if (state.engine && state.modelId === modelId) return state.engine;
    if (state.engine && state.modelId !== modelId) {
      await unload();
    }

    const diag = await diagnoseWebGPU();
    if (!diag.ok) {
      throw new Error(state.gpuIssue || diag.reason || "WebGPU unavailable");
    }

    const myGen = ++state.loadGen;
    state.loading = true;
    state.status = `Loading WebLLM on ${state.gpuLabel || "GPU"}…`;

    const { CreateMLCEngine } = await loadWebLLM();
    if (myGen !== state.loadGen) {
      state.loading = false;
      throw new Error("WebLLM load cancelled");
    }

    const engine = await CreateMLCEngine(modelId, {
      initProgressCallback: (p) => {
        if (myGen === state.loadGen) {
          state.status = `Loading WebLLM ${Math.round((p.progress || 0) * 100)}%`;
        }
      },
    });

    if (myGen !== state.loadGen) {
      state.loading = false;
      await disposeEngine(engine);
      throw new Error("WebLLM load cancelled");
    }

    state.engine = engine;
    state.modelId = modelId;
    state.ready = true;
    state.loading = false;
    state.status = `WebLLM ready (${state.gpuLabel || "GPU"})`;
    await postReady(true);
    return state.engine;
  }

  async function handleRequest(ev) {
    const { id, messages, stream } = ev;
    if (!id || !messages) return;
    try {
      if (!state.engine) throw new Error("WebLLM engine not loaded");
      if (stream) {
        const chunks = await state.engine.chat.completions.create({ messages, stream: true });
        for await (const chunk of chunks) {
          const delta = chunk.choices?.[0]?.delta?.content;
          if (delta) await fulfill(id, { chunk: delta });
        }
        await fulfill(id, { done: true });
      } else {
        const out = await state.engine.chat.completions.create({ messages });
        const text = out.choices?.[0]?.message?.content || "";
        await fulfill(id, { chunk: text, done: true });
      }
    } catch (e) {
      await fulfill(id, { error: e.message || String(e) });
    }
  }

  function formatInitError(err) {
    const msg = err?.message || String(err);
    if (/compatible gpu/i.test(msg)) {
      return (
        `WebGPU rejected your GPU (${state.gpuLabel || "detected"}). ${TROUBLESHOOT} ` +
        "New GPUs (e.g. RTX 50-series) may need the latest Chrome + drivers."
      );
    }
    if (/createRequire|require is not defined/i.test(msg)) {
      return "WebLLM bundle load failed — hard-refresh the page (Ctrl+Shift+R).";
    }
    if (state.gpuIssue) return state.gpuIssue;
    return `WebLLM init failed: ${msg}`;
  }

  async function unloadImpl() {
    state.loadGen += 1;
    if (state.unsub) {
      state.unsub();
      state.unsub = null;
    }
    const engine = state.engine;
    state.engine = null;
    state.modelId = null;
    state.ready = false;
    state.loading = false;
    state.gpuIssue = "";
    state.status = "WebLLM unloading…";
    await postReady(false);
    await disposeEngine(engine);
    state.status = "WebLLM unloaded (browser GPU freed)";
    console.info("[mayaWebLLM] unload complete");
  }

  function unload() {
    if (!unloadPromise) {
      unloadPromise = unloadImpl().finally(() => {
        unloadPromise = null;
      });
    }
    return unloadPromise;
  }

  function bindUnloadEvents() {
    if (!state._pagehideBound) {
      state._pagehideBound = true;
      window.addEventListener("pagehide", () => {
        if (state.engine) unload();
      });
    }
    if (state.unloadSub || !window.mayaAgentEvents) return;
    state.unloadSub = window.mayaAgentEvents.subscribe((ev) => {
      if (ev.type === "webllm_unload") unload();
    });
  }

  async function init(providerWebllm, modelId) {
    bindUnloadEvents();
    if (!providerWebllm) {
      await unload();
      return;
    }
    try {
      await ensureEngine(modelId);
      if (!state.unsub && window.mayaAgentEvents) {
        state.unsub = window.mayaAgentEvents.subscribe((ev) => {
          if (ev.type === "webllm_request") handleRequest(ev);
        });
      }
    } catch (e) {
      await unload();
      state.status = formatInitError(e);
      await postReady(false);
    }
  }

  setTimeout(bindUnloadEvents, 0);

  window.mayaWebLLMBridge = {
    get status() {
      return state.status;
    },
    get ready() {
      return state.ready;
    },
    get loading() {
      return state.loading;
    },
    get gpuLabel() {
      return state.gpuLabel;
    },
    get gpuIssue() {
      return state.gpuIssue;
    },
    get troubleshoot() {
      return TROUBLESHOOT;
    },
    init,
    unload,
    diagnose: diagnoseWebGPU,
  };
})();
