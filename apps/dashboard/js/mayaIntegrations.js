/** Settings → Integrations — Google connect and ComfyUI status. */
document.addEventListener("alpine:init", () => {
  Alpine.data("mayaIntegrations", () => ({
    loading: true,
    error: "",
    disconnecting: false,
    bandcampUsername: "",
    bandcampSaving: false,
    bandcampTesting: false,
    bandcampError: "",
    bandcampStatus: {
      connected: false,
      username: "",
      wishlist_count: 0,
      display_name: "",
    },
    status: {
      connected: false,
      email: "",
      permissions: {},
      connected_at: null,
    },
    imagineHealth: null,
    imagineHealthTesting: false,
    imagineCapability: null,
    permissionKeys: [
      "mailbox_read",
      "mailbox_send",
      "calendar_read",
      "calendar_write",
    ],
    permissionMeta: {
      mailbox_read: {
        label: "Mailbox — read",
        hint: "Read inbox threads via Gmail",
      },
      mailbox_send: {
        label: "Mailbox — send",
        hint: "Compose and send email",
      },
      calendar_read: {
        label: "Calendar — read",
        hint: "View calendar events",
      },
      calendar_write: {
        label: "Calendar — write",
        hint: "Create and edit calendar events",
      },
    },

    async init() {
      await Promise.all([this.refresh(), this.refreshImagine(), this.refreshBandcamp()]);
    },

    async refresh() {
      this.loading = true;
      this.error = "";
      try {
        const res = await fetch("/api/integrations/google/status");
        if (res.status === 401) {
          this.error = "Sign in to manage integrations.";
          return;
        }
        if (!res.ok) {
          const data = await res.json().catch(() => ({}));
          this.error = data.detail || "Could not load integration status.";
          return;
        }
        this.status = await res.json();
        if (!this.status.permissions) {
          this.status.permissions = {};
        }
      } catch (_) {
        this.error = "Network error loading integrations.";
      } finally {
        this.loading = false;
      }
    },

    async refreshImagine() {
      try {
        const [healthR, statusR] = await Promise.all([
          fetch("/api/voice/settings/imagine-health", { method: "POST" }),
          fetch("/api/voice/agent/status"),
        ]);
        if (healthR.ok) {
          const data = await healthR.json();
          this.imagineHealth = data.health || null;
        }
        if (statusR.ok) {
          const st = await statusR.json();
          this.imagineCapability = st.capabilities?.imagine ?? null;
          if (!this.imagineHealth && st.imagine_health) {
            this.imagineHealth = st.imagine_health;
          }
        }
      } catch (_) {
        /* non-fatal — card shows offline */
      }
    },

    async testImagineConnection() {
      this.imagineHealthTesting = true;
      try {
        const r = await fetch("/api/voice/settings/imagine-health", { method: "POST" });
        if (!r.ok) throw new Error("ComfyUI health check failed");
        const data = await r.json();
        this.imagineHealth = data.health || null;
      } catch (e) {
        this.imagineHealth = { status: "error", detail: String(e.message || e) };
      } finally {
        this.imagineHealthTesting = false;
      }
    },

    openImagineSettings() {
      if (this.$root?.tab != null) {
        this.$root.tab = "imagine";
        const url = new URL(window.location.href);
        url.searchParams.set("tab", "imagine");
        window.history.replaceState({}, "", url);
        return;
      }
      window.location.href = "/settings?tab=imagine";
    },

    imagineStatusLabel() {
      const h = this.imagineHealth;
      if (!h) return "Unknown";
      if (h.status === "ok") return "Connected";
      if (h.status === "warn") return "Degraded";
      if (h.status === "skipped") return "Skipped";
      return "Offline";
    },

    imagineStatusClass() {
      const h = this.imagineHealth;
      if (!h) return "";
      if (h.status === "ok") return "operator";
      return "";
    },

    imagineWeightsSummary() {
      const weights = this.imagineHealth?.weights;
      if (!weights) return "";
      const parts = [];
      for (const key of ["zit", "krea2"]) {
        const probe = weights[key];
        if (!probe || typeof probe !== "object") continue;
        const label = key === "krea2" ? "Krea2" : "Z-Image";
        if (probe.ok) {
          parts.push(`${label}: ok`);
        } else if (key === "krea2" && probe.capability && probe.capability.ok === false) {
          const ver = probe.capability.comfyui_version || "unknown";
          parts.push(`${label}: needs ComfyUI 0.27+ (have ${ver})`);
        } else {
          const missing = Array.isArray(probe.missing) ? probe.missing.join(", ") : "missing";
          parts.push(`${label}: ${missing || "missing"}`);
        }
      }
      return parts.join(" · ");
    },

    async refreshBandcamp() {
      this.bandcampError = "";
      try {
        const res = await fetch("/api/integrations/bandcamp/status");
        if (res.status === 401) return;
        if (!res.ok) {
          const data = await res.json().catch(() => ({}));
          this.bandcampError = data.detail || "Could not load Bandcamp status.";
          return;
        }
        this.bandcampStatus = await res.json();
        if (this.bandcampStatus.username && !this.bandcampUsername) {
          this.bandcampUsername = this.bandcampStatus.username;
        }
      } catch (_) {
        this.bandcampError = "Network error loading Bandcamp status.";
      }
    },

    async saveBandcampUsername() {
      this.bandcampSaving = true;
      this.bandcampError = "";
      try {
        const res = await fetch("/api/integrations/bandcamp/username", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ username: this.bandcampUsername, enabled: true }),
        });
        const data = await res.json().catch(() => ({}));
        if (!res.ok) {
          this.bandcampError = data.detail || "Could not save Bandcamp username.";
          return;
        }
        const { ok: _ok, ...status } = data;
        this.bandcampStatus = status;
        if (status.username) this.bandcampUsername = status.username;
      } catch (_) {
        this.bandcampError = "Network error saving Bandcamp username.";
      } finally {
        this.bandcampSaving = false;
      }
    },

    async testBandcampConnection() {
      this.bandcampTesting = true;
      this.bandcampError = "";
      try {
        await this.saveBandcampUsername();
        if (!this.bandcampError) await this.refreshBandcamp();
      } finally {
        this.bandcampTesting = false;
      }
    },

    connectUrl(permissions) {
      const perms =
        permissions && permissions.length
          ? permissions
          : ["mailbox_read", "calendar_read"];
      return `/api/integrations/google/connect?permissions=${encodeURIComponent(perms.join(","))}`;
    },

    connectGoogle() {
      window.location.href = this.connectUrl(["mailbox_read", "calendar_read"]);
    },

    togglePermission(key) {
      const desired = { ...this.status.permissions };
      desired[key] = !desired[key];
      const enabled = this.permissionKeys.filter((k) => desired[k]);
      if (!enabled.length) {
        this.error = "At least one permission must remain enabled.";
        return;
      }
      window.location.href = this.connectUrl(enabled);
    },

    async disconnectGoogle() {
      if (!confirm("Disconnect Google and remove stored tokens?")) return;
      this.disconnecting = true;
      this.error = "";
      try {
        const res = await fetch("/api/integrations/google", { method: "DELETE" });
        if (!res.ok) {
          const data = await res.json().catch(() => ({}));
          this.error = data.detail || "Disconnect failed.";
          return;
        }
        await this.refresh();
      } catch (_) {
        this.error = "Network error during disconnect.";
      } finally {
        this.disconnecting = false;
      }
    },

    formatConnectedAt(iso) {
      if (!iso) return "";
      try {
        return new Date(iso).toLocaleString();
      } catch (_) {
        return iso;
      }
    },
  }));
});
