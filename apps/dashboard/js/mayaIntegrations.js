/** Settings → Integrations — Google connect and permission management. */
document.addEventListener("alpine:init", () => {
  Alpine.data("mayaIntegrations", () => ({
    loading: true,
    error: "",
    disconnecting: false,
    status: {
      connected: false,
      email: "",
      permissions: {},
      connected_at: null,
    },
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
      await this.refresh();
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
