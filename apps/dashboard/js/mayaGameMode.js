/** Game Mode panel — profiles, mGBA detection, bridge controls, live action log. */
document.addEventListener("alpine:init", () => {
  Alpine.store("mayaGame", {
    detected: false,
    bridgeRunning: false,
    autonomous: false,
    captureActive: false,
    syncFrom(panel) {
      this.detected = !!panel.detectedWindow;
      this.bridgeRunning = !!(panel.bridgeRunning || panel.status?.connected);
      this.autonomous = !!panel.status?.autonomous;
      this.captureActive = !!panel.gameCaptureActive;
    },
  });

  Alpine.data("mayaGameMode", () => ({
    loading: true,
    profiles: [],
    selectedProfile: "pokemon_gba",
    status: null,
    frameStatus: null,
    log: [],
    error: "",
    captureMode: "native_window",
    bridgeCmd: "",
    gameCaptureActive: false,
    goal: "",
    autonomousStarting: false,
    bridgeStarting: false,
    bridgeRunning: false,
    detectedWindow: "",
    windowNeedle: "mGBA",
    windowsChecked: false,
    analysisSecFast: 1,
    analysisSecSlow: 2.5,
    pollFps: 8,
    timingSaving: false,

    init() {
      this.refresh().finally(() => {
        this.loading = false;
      });
      this._unsub = window.mayaAgentEvents?.subscribe((ev) => this.onEvent(ev));
      this._pollTimer = setInterval(() => this.pollBridge(), 4000);
      return () => this.destroy();
    },

    destroy() {
      if (this._unsub) this._unsub();
      if (this._pollTimer) clearInterval(this._pollTimer);
      this._stopGameCapture();
    },

    syncStore() {
      Alpine.store("mayaGame").syncFrom(this);
    },

    onEvent(ev) {
      if (!ev?.type) return;
      if (ev.type === "game.turn") {
        const say = ev.say ? ` · "${ev.say}"` : "";
        const prog = ev.goal_progress ? ` [${ev.goal_progress}]` : "";
        this.pushLog(`turn ${ev.turn || "?"} · ${ev.action}${say}${prog}`);
        if (ev.goal_reached) {
          this.pushLog(`goal reached · ${ev.goal || this.goal}`);
        }
      }
      if (ev.type === "game.action") {
        this.pushLog(`action · ${ev.action}${ev.data ? " " + JSON.stringify(ev.data) : ""}`);
      }
      if (ev.type === "game.event") {
        this.pushLog(`event · ${ev.command || ""}`);
      }
      if (ev.type === "game.error") {
        this.pushLog(`error · ${ev.text || "unknown"}`);
      }
      if (ev.type === "game.session") {
        this.pushLog(`session · ${ev.action} ${ev.profile_id || ""}`);
      }
      if (ev.type === "game.autonomous") {
        if (ev.action === "start" && ev.goal) this.goal = ev.goal;
        this.pushLog(`autonomous · ${ev.action} ${ev.goal || ""}`);
        void this.refresh();
      }
    },

    pushLog(line) {
      const ts = new Date().toLocaleTimeString();
      const entry = `${ts}  ${line}`;
      this.log.unshift(entry);
      if (this.log.length > 80) this.log.pop();
    },

    async onProfileChange() {
      this.updateBridgeCmd();
      await this.detectWindows();
    },

    async detectWindows() {
      try {
        const r = await fetch(
          `/api/game/windows?profile_id=${encodeURIComponent(this.selectedProfile)}`,
          { credentials: "same-origin" },
        );
        const data = await r.json();
        this.windowsChecked = true;
        if (!data.ok) return;
        this.windowNeedle = data.title_substring || "mGBA";
        const wins = data.windows || [];
        if (wins.length) {
          this.detectedWindow = wins[0].title || "emulator window";
        } else {
          this.detectedWindow = "";
        }
        this.syncStore();
      } catch {
        this.windowsChecked = true;
      }
    },

    async pollBridge() {
      try {
        const r = await fetch("/api/game/bridge/status", { credentials: "same-origin" });
        const data = await r.json();
        this.bridgeRunning = !!data.running;
        this.syncStore();
      } catch {
        /* ignore */
      }
    },

    async refresh() {
      this.error = "";
      try {
        const [profR, statR, timingR] = await Promise.all([
          fetch("/api/game/profiles", { credentials: "same-origin" }),
          fetch("/api/game/status", { credentials: "same-origin" }),
          fetch(
            `/api/game/timing?profile_id=${encodeURIComponent(this.selectedProfile)}`,
            { credentials: "same-origin" },
          ),
        ]);
        if (!profR.ok) {
          this.error =
            profR.status === 401
              ? "Log in to use Game mode."
              : `Could not load profiles (HTTP ${profR.status}).`;
        }
        const prof = await profR.json();
        const stat = await statR.json();
        let timing = null;
        if (timingR.ok) {
          try {
            timing = await timingR.json();
          } catch {
            /* timing endpoint may return non-JSON on server error */
          }
        }
        if (prof.ok) {
          this.profiles = prof.profiles || [];
          if (this.profiles.length && !this.profiles.find((p) => p.id === this.selectedProfile)) {
            this.selectedProfile = this.profiles[0].id;
          }
        }
        if (stat.ok) {
          this.status = stat.session || {};
          this.frameStatus = stat.frame || {};
          if (this.status.bridge) {
            this.bridgeRunning = !!this.status.bridge.running;
          }
          if (this.status.goal && !this.goal) this.goal = this.status.goal;
        }
        if (timing?.ok && timing.timing) {
          const t = timing.timing;
          const fpsMin = Number(t.analysis_fps_min) || 0.125;
          const fpsMax = Number(t.analysis_fps_max) || 0.33;
          this.analysisSecSlow = Math.round((1 / fpsMin) * 10) / 10;
          this.analysisSecFast = Math.round((1 / fpsMax) * 10) / 10;
          this.pollFps = Number(t.poll_fps) || 4;
        }
        await this.detectWindows();
        await this.pollBridge();
        this.updateBridgeCmd();
        this.syncStore();
      } catch (e) {
        this.error = String(e.message || e);
      }
    },

    updateBridgeCmd() {
      const host = window.location.origin;
      let cmd =
        `python -m apps.game_bridge run --profile ${this.selectedProfile}` +
        ` --gateway ${host} --token <maya_op_session cookie>`;
      if (this.goal.trim()) {
        cmd += ` --goal "${this.goal.trim().replace(/"/g, '\\"')}"`;
      }
      if (this.captureMode) cmd += ` --capture ${this.captureMode}`;
      this.bridgeCmd = cmd;
    },

    async startBridge() {
      this.bridgeStarting = true;
      this.error = "";
      this._stopGameCapture();
      const goal = (this.goal || "").trim();
      try {
        if (goal) {
          await fetch("/api/game/autonomous/start", {
            method: "POST",
            credentials: "same-origin",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ goal, profile_id: this.selectedProfile }),
          });
        }
        const r = await fetch("/api/game/bridge/start", {
          method: "POST",
          credentials: "same-origin",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ profile_id: this.selectedProfile, goal }),
        });
        const data = await r.json();
        if (!data.ok) {
          this.error = data.detail || data.error || "Could not start bridge";
          return;
        }
        this.bridgeRunning = true;
        this.pushLog(`bridge · started (pid ${data.pid || "?"})`);
        if (goal) this.pushLog(`autonomous · goal set — ${goal}`);
        await this.refresh();
      } catch (e) {
        this.error = String(e.message || e);
      } finally {
        this.bridgeStarting = false;
        this.syncStore();
      }
    },

    async stopBridge() {
      try {
        await fetch("/api/game/bridge/stop", { method: "POST", credentials: "same-origin" });
        this.bridgeRunning = false;
        this.pushLog("bridge · stopped");
        this.syncStore();
      } catch (e) {
        this.error = String(e.message || e);
      }
    },

    async startAutonomous() {
      const goal = (this.goal || "").trim();
      if (!goal) {
        this.error = "Enter a goal first (e.g. get through Professor Oak intro)";
        return;
      }
      this.autonomousStarting = true;
      this.error = "";
      try {
        const r = await fetch("/api/game/autonomous/start", {
          method: "POST",
          credentials: "same-origin",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ goal, profile_id: this.selectedProfile }),
        });
        const data = await r.json();
        if (!data.ok) {
          this.error = data.detail || data.error || "Could not start autonomous play";
          return;
        }
        this.pushLog(`autonomous · goal set — ${goal}`);
        this.updateBridgeCmd();
        await this.refresh();
      } catch (e) {
        this.error = String(e.message || e);
      } finally {
        this.autonomousStarting = false;
      }
    },

    async stopAutonomous() {
      try {
        await fetch("/api/game/autonomous/stop", {
          method: "POST",
          credentials: "same-origin",
        });
        this.pushLog("autonomous · stopped");
        await this.refresh();
      } catch (e) {
        this.error = String(e.message || e);
      }
    },

    async stopSession() {
      try {
        await fetch("/api/game/session/stop", {
          method: "POST",
          credentials: "same-origin",
        });
        this.pushLog("session · stopped");
        await this.refresh();
      } catch (e) {
        this.error = String(e.message || e);
      }
    },

    async saveGameTiming() {
      this.timingSaving = true;
      this.error = "";
      try {
        const fast = Math.max(1, Number(this.analysisSecFast) || 3);
        const slow = Math.max(fast, Number(this.analysisSecSlow) || 8);
        const r = await fetch("/api/game/timing", {
          method: "PATCH",
          credentials: "same-origin",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            poll_fps: Number(this.pollFps) || 6,
            analysis_fps_max: 1 / fast,
            analysis_fps_min: 1 / slow,
          }),
        });
        let data = {};
        try {
          data = await r.json();
        } catch {
          this.error = `Could not save timing (HTTP ${r.status})`;
          return;
        }
        if (!data.ok) {
          this.error = data.detail || data.error || "Could not save timing";
          return;
        }
        this.pushLog(
          `timing · capture ${this.pollFps} fps · think every ${fast}–${slow}s`,
        );
      } catch (e) {
        this.error = String(e.message || e);
      } finally {
        this.timingSaving = false;
      }
    },

    async startBrowserCapture() {
      if (this.bridgeRunning || this.status?.bridge?.running) {
        this.error =
          "Bridge is already capturing mGBA — stop Share emulator. Use Start bridge instead.";
        return;
      }
      if (!window.mayaVisionCapture) {
        this.error = "Vision capture module not loaded";
        return;
      }
      this._stopGameCapture();
      try {
        const pollMs = Math.max(100, Math.round(1000 / (Number(this.pollFps) || 4)));
        const result = await window.mayaVisionCapture.startShare({
          label: `game:${this.selectedProfile}`,
          intervalMs: pollMs,
          gameMode: true,
        });
        if (!result?.ok) {
          this.error = result?.error || "Could not start screen share";
          return;
        }
        this.gameCaptureActive = true;
        this.syncStore();
        this.pushLog("capture · browser share started (game frame push)");
      } catch (e) {
        this.error = String(e.message || e);
      }
    },

    _stopGameCapture() {
      if (this.gameCaptureActive && window.mayaVisionCapture) {
        window.mayaVisionCapture.stopShare();
        this.gameCaptureActive = false;
        this.syncStore();
      }
    },

    panicStop() {
      this._stopGameCapture();
      void this.stopBridge();
      void this.stopAutonomous();
      void this.stopSession();
    },
  }));
});
