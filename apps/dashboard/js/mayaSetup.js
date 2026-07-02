/* mayaSetup.js — Alpine component for first-run admin setup */

document.addEventListener('alpine:init', () => {
  Alpine.data('mayaSetup', () => ({
    username: '',
    displayName: '',
    password: '',
    confirm: '',
    showPw: false,
    showConfirm: false,
    loading: false,
    error: '',
    shaking: false,

    async init() {
      try {
        const res = await fetch('/api/auth/me');
        if (res.ok) {
          const data = await res.json();
          if (!data.setup_required) {
            window.location.href = '/login';
          }
        }
      } catch (_) {}
    },

    submitLabel() {
      return this.loading ? 'Creating account…' : 'Create Admin Account';
    },

    async submit() {
      this.error = '';
      if (!this.username.trim()) return this._shake('Username is required.');
      if (!this.password) return this._shake('Password is required.');
      if (this.password.length < 8) return this._shake('Password must be at least 8 characters.');
      if (this.password !== this.confirm) return this._shake('Passwords do not match.');

      this.loading = true;
      try {
        const res = await fetch('/api/operators', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            username: this.username.trim(),
            display_name: this.displayName.trim() || this.username.trim(),
            password: this.password,
            role: 'admin',
          }),
        });
        const data = await res.json().catch(() => ({}));
        if (!res.ok) {
          this._shake(data.detail || 'Could not create account.');
          return;
        }
        window.location.href = '/login';
      } catch (e) {
        this._shake('Network error — could not reach server.');
      } finally {
        this.loading = false;
      }
    },

    _shake(msg) {
      this.error = msg;
      this.shaking = true;
      setTimeout(() => { this.shaking = false; }, 450);
    },
  }));
});
