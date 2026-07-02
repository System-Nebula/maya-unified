/* mayaAdminUsers.js — Alpine component for admin-users.html */

function mayaAdminUsers() {
  return {
    operators: [],
    currentUserId: '',
    pageError: '',

    showCreate: false,
    showEdit: false,
    editTarget: null,
    deleteTarget: null,

    form: { username: '', display_name: '', role: 'operator', password: '' },
    modalError: '',
    modalSaving: false,

    async init() {
      try {
        const me = await fetch('/api/auth/me').then(r => r.json());
        if (!me.authenticated) { window.location.href = '/login'; return; }
        if (me.role !== 'admin') { window.location.href = '/'; return; }
        this.currentUserId = me.id;
        await this.loadOperators();
      } catch (e) {
        this.pageError = 'Failed to load. ' + e.message;
      }
    },

    async loadOperators() {
      const res = await fetch('/api/operators');
      if (!res.ok) { this.pageError = 'Could not load operators.'; return; }
      const data = await res.json();
      this.operators = data.operators || [];
    },

    openEdit(op) {
      this.editTarget = op;
      this.form = { username: op.username, display_name: op.display_name, role: op.role, password: '' };
      this.modalError = '';
      this.showEdit = true;
    },

    confirmDelete(op) {
      this.deleteTarget = op;
    },

    closeModal() {
      this.showCreate = false;
      this.showEdit = false;
      this.editTarget = null;
      this.modalError = '';
      this.form = { username: '', display_name: '', role: 'operator', password: '' };
    },

    async saveModal() {
      this.modalError = '';
      if (this.showCreate) {
        if (!this.form.username.trim()) { this.modalError = 'Username is required.'; return; }
        if (!this.form.password || this.form.password.length < 8) {
          this.modalError = 'Password must be at least 8 characters.'; return;
        }
      }
      this.modalSaving = true;
      try {
        let res;
        if (this.showEdit) {
          const body = { display_name: this.form.display_name, role: this.form.role };
          if (this.form.password) body.password = this.form.password;
          res = await fetch(`/api/operators/${this.editTarget.id}`, {
            method: 'PATCH',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(body),
          });
        } else {
          res = await fetch('/api/operators', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
              username: this.form.username.trim(),
              display_name: this.form.display_name.trim() || this.form.username.trim(),
              role: this.form.role,
              password: this.form.password,
            }),
          });
        }
        const data = await res.json().catch(() => ({}));
        if (!res.ok) { this.modalError = data.detail || 'Operation failed.'; return; }
        this.closeModal();
        await this.loadOperators();
      } catch (e) {
        this.modalError = 'Network error.';
      } finally {
        this.modalSaving = false;
      }
    },

    async toggleBan(op) {
      const ban = !op.is_banned;
      const action = ban ? 'ban' : 'unban';
      if (!confirm(`${ban ? 'Ban' : 'Unban'} ${op.display_name}?`)) return;
      const res = await fetch(`/api/admin/operators/${op.id}/${action}`, { method: 'POST' });
      if (!res.ok) {
        const d = await res.json().catch(() => ({}));
        this.pageError = d.detail || `${action} failed.`;
        return;
      }
      await this.loadOperators();
    },

    async doDelete() {
      if (!this.deleteTarget) return;
      this.modalSaving = true;
      try {
        const res = await fetch(`/api/operators/${this.deleteTarget.id}`, { method: 'DELETE' });
        if (!res.ok) {
          const d = await res.json().catch(() => ({}));
          this.pageError = d.detail || 'Delete failed.';
        }
        this.deleteTarget = null;
        await this.loadOperators();
      } catch (e) {
        this.pageError = 'Network error during delete.';
      } finally {
        this.modalSaving = false;
      }
    },

    reltime(iso) {
      const ms = Date.now() - new Date(iso).getTime();
      const m = Math.floor(ms / 60000);
      if (m < 1) return 'just now';
      if (m < 60) return `${m}m ago`;
      const h = Math.floor(m / 60);
      if (h < 24) return `${h}h ago`;
      return `${Math.floor(h / 24)}d ago`;
    },

    datestr(iso) {
      return new Date(iso).toLocaleDateString();
    },
  };
}
