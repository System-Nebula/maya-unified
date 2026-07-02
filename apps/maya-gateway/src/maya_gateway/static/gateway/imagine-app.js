/** Imagine Alpine app — composer, SSE, poll fallback, leaderboard. */
(function applyImagineTheme() {
  try {
    let id = localStorage.getItem("maya-ui-theme") || "unified";
    if (id === "gateway") id = "industrial";
    if (id === "hermes") id = "unified";
    document.documentElement.dataset.mayaTheme = id;
  } catch (_) {}
})();

function readImagineBootstrap() {
  const el = document.getElementById("imagine-bootstrap");
  if (!el) return { battles: [], default_workflow_id: "z-image-turbo-t2i" };
  try {
    return JSON.parse(el.textContent);
  } catch {
    return { battles: [], default_workflow_id: "z-image-turbo-t2i" };
  }
}

document.addEventListener("alpine:init", () => {
  Alpine.data("imagineApp", () => ({
    prompt: "",
    submitting: false,
    pollTimers: new Map(),
    defaultWorkflowId: "z-image-turbo-t2i",

    init() {
      const boot = readImagineBootstrap();
      this.defaultWorkflowId = boot.default_workflow_id || "z-image-turbo-t2i";
      const store = Alpine.store("imagineStore");
      for (const b of boot.battles || []) {
        if (b && b.battle_id) store.applyDelta({ type: "battle_upsert", battle: b });
      }
      this.$nextTick(() => {
        const feed = document.getElementById("gateway-feed");
        if (feed) GatewayFeedRenderer.mount(feed, store);
      });
      this.connectSse();
      this.loadLeaderboard();
      window.addEventListener("gateway:leaderboardRefresh", () => this.loadLeaderboard());
    },

    connectSse() {
      const store = Alpine.store("imagineStore");
      const es = new EventSource("/gateway/imagine/queue/stream");
      es.onopen = () => {
        store.sseConnected = true;
      };
      es.onmessage = (e) => {
        try {
          const data = JSON.parse(e.data);
          if (data.type === "battle" || data.battle_id) {
            store.applyDelta({ type: "battle_upsert", battle: data });
            if (data.state === "voting" || data.state === "resolved") {
              this.stopPoll(data.battle_id);
            }
          } else if (data.job_id) {
            store.applyDelta({ type: "job_upsert", ...data });
          }
        } catch (_) {
          /* heartbeat */
        }
      };
      es.onerror = () => {
        store.sseConnected = false;
      };
    },

    startPoll(battleId) {
      if (this.pollTimers.has(battleId)) return;
      const tick = async () => {
        const resp = await fetch(`/gateway/imagine/battle/${battleId}?format=json`);
        if (!resp.ok) return;
        const data = await resp.json();
        if (data.battle) {
          Alpine.store("imagineStore").applyDelta({ type: "battle_upsert", battle: data.battle });
          if (data.battle.state !== "generating") this.stopPoll(battleId);
        }
      };
      tick();
      const id = setInterval(tick, 2000);
      this.pollTimers.set(battleId, id);
    },

    stopPoll(battleId) {
      const id = this.pollTimers.get(battleId);
      if (id) {
        clearInterval(id);
        this.pollTimers.delete(battleId);
      }
    },

    async loadLeaderboard() {
      try {
        const resp = await fetch("/gateway/imagine/leaderboard?format=json");
        if (!resp.ok) return;
        const data = await resp.json();
        const el = document.getElementById("imagine-leaderboard");
        if (!el || !data.candidates) return;
        el.innerHTML = data.candidates
          .slice(0, 6)
          .map(
            (c) =>
              `<span>${c.name}: ${c.rating} ELO (${Math.round((c.win_rate || 0) * 100)}%)</span>`
          )
          .join("");
      } catch (_) {
        /* ignore */
      }
    },

    async submit() {
      const text = this.prompt.trim();
      if (!text || this.submitting) return;
      this.submitting = true;
      const fd = new FormData();
      fd.append("prompt", text);
      fd.append("workflow_id", this.defaultWorkflowId);
      fd.append("arena_mode", "default");
      try {
        const resp = await fetch("/gateway/imagine/generate", {
          method: "POST",
          body: fd,
          headers: { Accept: "application/json" },
        });
        if (resp.ok) {
          const data = await resp.json();
          if (data.battle) {
            Alpine.store("imagineStore").applyDelta({ type: "battle_upsert", battle: data.battle });
            this.startPoll(data.battle.battle_id);
            this.prompt = "";
            this.$nextTick(() => {
              const feed = document.getElementById("gateway-feed");
              if (feed) feed.scrollTop = feed.scrollHeight;
            });
          }
        }
      } finally {
        this.submitting = false;
      }
    },

    onKeydown(e) {
      if (e.key === "Enter" && !e.shiftKey) {
        e.preventDefault();
        this.submit();
      }
    },
  }));
});
