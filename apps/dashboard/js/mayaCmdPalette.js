/** cmd_registry rollout tray — presentation only; no execution. */
(function () {
  function _normalize(value) {
    return String(value || "").trim().toLowerCase();
  }

  function _inCmdNamePhase(text) {
    return /^\/[^\s]*$/.test(String(text || ""));
  }

  function _scoreCmd(cmd, query) {
    if (!query) return 0;
    const haystacks = [
      cmd.name,
      cmd.description,
      ...(cmd.aliases || []),
      ...(cmd.tags || []),
      ...(cmd.examples || []),
    ].map(_normalize);
    const q = _normalize(query);
    for (const hay of haystacks) {
      if (hay === q) return 100;
      if (hay.startsWith(q)) return 80;
      if (hay.includes(q)) return 40;
    }
    return 0;
  }

  function _visibleForDashboard(cmd) {
    const surfaces = cmd.surfaces || [];
    return surfaces.includes("dashboard") || surfaces.includes("chat");
  }

  document.addEventListener("alpine:init", () => {
    Alpine.store("mayaCmdPalette", {
      open: false,
      loading: false,
      error: "",
      cmds: [],
      query: "",
      selectedIndex: 0,

      async load() {
        if (this.loading) return;
        this.loading = true;
        this.error = "";
        try {
          const res = await fetch("/api/cmds?surface=dashboard");
          if (!res.ok) throw new Error(`discovery failed (${res.status})`);
          const data = await res.json();
          this.cmds = (data.cmds || []).filter(_visibleForDashboard);
        } catch (err) {
          this.error = String(err.message || err);
          this.cmds = [];
        } finally {
          this.loading = false;
        }
      },

      grouped() {
        const groups = new Map();
        for (const cmd of this.filtered()) {
          const category = cmd.category || "Utilities";
          if (!groups.has(category)) groups.set(category, []);
          groups.get(category).push(cmd);
        }
        return [...groups.entries()].map(([category, items]) => ({ category, items }));
      },

      filtered() {
        const draft = Alpine.store("mayaConversation")?.draft || "";
        const slashQuery = draft.startsWith("/") ? draft.slice(1).trim() : "";
        const query = _normalize(this.query || slashQuery);
        const items = this.cmds.slice();
        if (!query) return items;
        return items
          .map((cmd) => ({ cmd, score: _scoreCmd(cmd, query) }))
          .filter((row) => row.score > 0)
          .sort((a, b) => b.score - a.score || a.cmd.name.localeCompare(b.cmd.name))
          .map((row) => row.cmd);
      },

      flatItems() {
        return this.grouped().flatMap((group) => group.items);
      },

      openTray() {
        this.open = true;
        if (!this.cmds.length) this.load();
      },

      closeTray() {
        this.open = false;
        this.selectedIndex = 0;
      },

      toggleTray() {
        if (this.open) this.closeTray();
        else this.openTray();
      },

      onDraftChange(value) {
        const text = String(value || "");
        if (_inCmdNamePhase(text)) {
          this.open = true;
          if (!this.cmds.length && !this.loading) this.load();
          this.selectedIndex = 0;
        } else {
          this.closeTray();
        }
      },

      select(cmd) {
        const convo = Alpine.store("mayaConversation");
        if (!convo || !cmd) return;
        const required = (cmd.parameters || []).find((p) => p.required);
        const base = `/${cmd.name}`;
        convo.draft = required ? `${base} ` : `${base} `;
        this.closeTray();
        requestAnimationFrame(() => {
          document.querySelector(".md-composer .md-textarea")?.focus();
        });
      },

      selectCurrent() {
        const items = this.flatItems();
        if (!items.length) return false;
        const idx = Math.max(0, Math.min(this.selectedIndex, items.length - 1));
        this.select(items[idx]);
        return true;
      },

      moveSelection(delta) {
        const items = this.flatItems();
        if (!items.length) return;
        const next = this.selectedIndex + delta;
        if (next < 0) this.selectedIndex = items.length - 1;
        else if (next >= items.length) this.selectedIndex = 0;
        else this.selectedIndex = next;
      },

      handleKeydown(event) {
        if (!this.open) return false;
        if (event.key === "ArrowDown") {
          event.preventDefault();
          this.moveSelection(1);
          return true;
        }
        if (event.key === "ArrowUp") {
          event.preventDefault();
          this.moveSelection(-1);
          return true;
        }
        if (event.key === "Tab" || event.key === "Enter") {
          event.preventDefault();
          this.selectCurrent();
          return true;
        }
        if (event.key === "Escape") {
          event.preventDefault();
          this.closeTray();
          return true;
        }
        return false;
      },
    });
  });

  window.mayaCmdPalette = {
    handleComposerKeydown(event) {
      const store = window.Alpine?.store("mayaCmdPalette");
      if (!store) return false;
      return store.handleKeydown(event);
    },
    onDraftChange(value) {
      const store = window.Alpine?.store("mayaCmdPalette");
      if (!store) return;
      store.onDraftChange(value);
    },
  };
})();
