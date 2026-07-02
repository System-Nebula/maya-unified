/* mayaAdminWorkspaces.js — admin cross-operator workspace management */

function mayaAdminWorkspaces() {
  return {
    workspaces: [],
    selectedId: '',
    conversation: { total: 0, messages: [] },
    personalities: { active: '', personalities: {} },
    pageError: '',
    loading: false,
    convOffset: 0,
    convLimit: 50,

    async init() {
      try {
        const me = await fetch('/api/auth/me').then((r) => r.json());
        if (!me.authenticated) {
          window.location.href = '/login';
          return;
        }
        if (me.role !== 'admin') {
          window.location.href = '/';
          return;
        }
        await this.loadWorkspaces();
      } catch (e) {
        this.pageError = 'Failed to load. ' + e.message;
      }
    },

    async loadWorkspaces() {
      const res = await fetch('/api/admin/workspaces');
      if (!res.ok) {
        this.pageError = 'Could not load workspaces.';
        return;
      }
      const data = await res.json();
      this.workspaces = data.workspaces || [];
      if (!this.selectedId && this.workspaces.length) {
        this.selectedId = this.workspaces[0].id;
        await this.loadSelected();
      }
    },

    selectedWorkspace() {
      return this.workspaces.find((w) => w.id === this.selectedId) || null;
    },

    async onSelectChange() {
      this.convOffset = 0;
      await this.loadSelected();
    },

    async loadSelected() {
      if (!this.selectedId) return;
      this.loading = true;
      this.pageError = '';
      try {
        const [convRes, persRes] = await Promise.all([
          fetch(
            `/api/admin/operators/${this.selectedId}/conversation?limit=${this.convLimit}&offset=${this.convOffset}`
          ),
          fetch(`/api/admin/operators/${this.selectedId}/personalities`),
        ]);
        if (!convRes.ok || !persRes.ok) {
          this.pageError = 'Could not load workspace data.';
          return;
        }
        this.conversation = await convRes.json();
        this.personalities = await persRes.json();
      } catch (e) {
        this.pageError = String(e.message || e);
      } finally {
        this.loading = false;
      }
    },

    personalityList() {
      const p = this.personalities.personalities || {};
      return Object.entries(p).map(([slug, entry]) => ({
        slug,
        name: (entry && entry.name) || slug,
        flagged: !!(entry && entry.flagged),
      }));
    },

    async clearHistory() {
      if (!this.selectedId) return;
      if (!confirm('Delete all conversation history for this operator?')) return;
      const res = await fetch(`/api/admin/operators/${this.selectedId}/conversation`, {
        method: 'DELETE',
      });
      if (!res.ok) {
        const d = await res.json().catch(() => ({}));
        this.pageError = d.detail || 'Could not clear history.';
        return;
      }
      this.convOffset = 0;
      await this.loadWorkspaces();
      await this.loadSelected();
    },

    async deletePersonality(slug) {
      if (!confirm(`Delete personality "${slug}"?`)) return;
      const res = await fetch(
        `/api/admin/operators/${this.selectedId}/personalities/${encodeURIComponent(slug)}`,
        { method: 'DELETE' }
      );
      if (!res.ok) {
        const d = await res.json().catch(() => ({}));
        this.pageError = d.detail || 'Delete failed.';
        return;
      }
      await this.loadWorkspaces();
      await this.loadSelected();
    },

    async toggleFlag(slug, flagged) {
      const res = await fetch(
        `/api/admin/operators/${this.selectedId}/personalities/${encodeURIComponent(slug)}/flag`,
        {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ flagged }),
        }
      );
      if (!res.ok) {
        const d = await res.json().catch(() => ({}));
        this.pageError = d.detail || 'Flag update failed.';
        return;
      }
      await this.loadSelected();
    },

    async toggleBan(ws) {
      const ban = !ws.is_banned;
      const action = ban ? 'ban' : 'unban';
      if (!confirm(`${ban ? 'Ban' : 'Unban'} ${ws.display_name}?`)) return;
      const res = await fetch(`/api/admin/operators/${ws.id}/${action}`, { method: 'POST' });
      if (!res.ok) {
        const d = await res.json().catch(() => ({}));
        this.pageError = d.detail || `${action} failed.`;
        return;
      }
      await this.loadWorkspaces();
    },

    convPrev() {
      this.convOffset = Math.max(0, this.convOffset - this.convLimit);
      this.loadSelected();
    },

    convNext() {
      if (this.convOffset + this.convLimit < (this.conversation.total || 0)) {
        this.convOffset += this.convLimit;
        this.loadSelected();
      }
    },

    get convHasPrev() {
      return this.convOffset > 0;
    },

    get convHasNext() {
      return this.convOffset + this.convLimit < (this.conversation.total || 0);
    },

    formatTs(iso) {
      if (!iso) return '';
      try {
        return new Date(iso).toLocaleString();
      } catch {
        return iso;
      }
    },
  };
}
