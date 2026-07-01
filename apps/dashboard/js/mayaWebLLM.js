/** Optional WebLLM browser chat (@mlc-ai/web-llm) for Conversation panel. */
document.addEventListener("alpine:init", () => {
  Alpine.data("mayaWebLLM", () => ({
    prompt: "",
    reply: "",
    status: "WebGPU check…",
    ready: false,
    loading: false,
    engine: null,
    modelId: "Llama-3.1-8B-Instruct-q4f16_1-MLC",

    async init() {
      if (!navigator.gpu) {
        this.status = "WebGPU unavailable — use LM Studio or LiteLLM for server reasoning.";
        return;
      }
      try {
        const r = await fetch("/api/voice/settings");
        if (r.ok) {
          const data = await r.json();
          this.modelId = data.settings?.reasoning?.webllm?.model_id || this.modelId;
        }
        const { CreateMLCEngine } = await import(
          "https://esm.run/@mlc-ai/web-llm"
        );
        this.status = "Loading model…";
        this.engine = await CreateMLCEngine(this.modelId, {
          initProgressCallback: (p) => {
            this.status = `Loading ${Math.round((p.progress || 0) * 100)}%`;
          },
        });
        this.ready = true;
        this.status = "WebLLM ready";
      } catch (e) {
        this.status = "WebLLM init failed: " + (e.message || e);
      }
    },

    async send() {
      if (!this.engine || !this.prompt.trim()) return;
      this.loading = true;
      try {
        const messages = [{ role: "user", content: this.prompt.trim() }];
        const out = await this.engine.chat.completions.create({ messages });
        const text = out.choices?.[0]?.message?.content || "";
        const parent = this.$root;
        if (parent.turns) {
          parent.turns.push({ role: "operator", text: this.prompt });
          parent.turns.push({ role: "maya", text });
        }
        this.prompt = "";
      } catch (e) {
        this.status = "Error: " + (e.message || e);
      } finally {
        this.loading = false;
      }
    },
  }));
});
