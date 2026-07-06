/** Tools runtime — list all registered tools + MCP servers (qwen3 parity). */
document.addEventListener("alpine:init", () => {
  Alpine.data("mayaToolsPanel", () => ({
    loading: true,
    enabled: false,
    mode: "auto",
    maxRounds: 3,
    tools: [],
    mcpServers: [],
    mcpHint: "",
    mcpEnabled: false,
    mcpPackageInstalled: null,
    toolLog: [],
    error: "",
    _unsub: null,

    get agentReady() {
      return Alpine.store("mayaShell")?.ready || false;
    },

    init() {
      if (this._unsub) {
        this._unsub();
        this._unsub = null;
      }
      this._unsub = window.mayaAgentEvents?.subscribe((ev) => this.onEvent(ev));
      this.loading = true;
      this.refresh().finally(() => {
        this.loading = false;
      });
      return () => this.destroy();
    },

    destroy() {
      if (this._unsub) this._unsub();
    },

    onEvent(ev) {
      if (ev.type === "tool_start") {
        const args = ev.args ? ` ${JSON.stringify(ev.args).slice(0, 80)}` : "";
        this.pushLog(`${ev.tool} · running${args}`);
      }
      if (ev.type === "tool_end") {
        const res = ev.result ? ` → ${String(ev.result).slice(0, 100)}` : "";
        this.pushLog(`${ev.tool} · done${res}`);
      }
      if (ev.type === "tool_trace" && Array.isArray(ev.trace)) {
        for (const entry of ev.trace) {
          const args = entry.args ? ` ${JSON.stringify(entry.args).slice(0, 60)}` : "";
          this.pushLog(`${entry.tool} · trace${args}`);
        }
      }
      if (ev.type === "ready" && ev.value) this.refresh();
    },

    pushLog(line) {
      const ts = new Date().toLocaleTimeString();
      const entry = `${ts}  ${line}`;
      if (this.toolLog[0] === entry) return;
      this.toolLog.unshift(entry);
      if (this.toolLog.length > 40) this.toolLog.pop();
    },

    async refresh() {
      this.error = "";
      try {
        const r = await fetch("/api/voice/agent/tools-status");
        const d = await r.json();
        if (!d.ok) {
          this.error = d.error || "Could not load tools";
          return;
        }
        this.enabled = !!d.enabled;
        this.mode = d.mode || "auto";
        this.maxRounds = d.max_rounds ?? 3;
        this.tools = d.tools || [];
        const mcp = d.mcp || {};
        this.mcpHint = mcp.hint || "";
        this.mcpEnabled = mcp.enabled !== false;
        this.mcpPackageInstalled = mcp.package_installed ?? null;
        const servers = mcp.servers || {};
        this.mcpServers = Object.keys(servers).map((name) => ({
          name,
          connected: !!servers[name].connected,
          tools: servers[name].tools,
          error: servers[name].error,
        }));
      } catch (e) {
        this.error = String(e.message || e);
      }
    },

    get toolGroups() {
      const groups = {};
      for (const t of this.tools) {
        const g = t.group || "builtin";
        if (!groups[g]) groups[g] = [];
        groups[g].push(t);
      }
      return Object.entries(groups).sort((a, b) => a[0].localeCompare(b[0]));
    },

    toolNamesLine(items) {
      return (items || []).map((t) => t.name).join(" · ");
    },

    get allToolsLine() {
      return this.tools.map((t) => t.name).join(" · ");
    },
  }));
});
