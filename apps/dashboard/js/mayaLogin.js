/* mayaLogin.js — Alpine component for login.html */

document.addEventListener('alpine:init', () => {
  Alpine.data('mayaLogin', () => ({
    username: '',
    password: '',
    showPw: false,
    loading: false,
    error: '',
    shaking: false,

    async init() {
      try {
        const res = await fetch('/api/auth/me');
        if (res.ok) {
          const data = await res.json();
          if (data.authenticated) {
            this._redirect();
          }
        }
      } catch (_) {
        // network error — stay on login page
      }
    },

    submitLabel() {
      return this.loading ? 'Signing in…' : 'Sign In';
    },

    async submit() {
      this.error = '';
      if (!this.username.trim() || !this.password) {
        this._shake('Username and password are required.');
        return;
      }
      this.loading = true;
      try {
        const res = await fetch('/api/auth/login', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ username: this.username.trim(), password: this.password }),
        });
        const data = await res.json().catch(() => ({}));
        if (!res.ok) {
          this._shake(data.detail || 'Invalid username or password.');
          return;
        }
        this._redirect();
      } catch (e) {
        this._shake('Network error — could not reach server.');
      } finally {
        this.loading = false;
      }
    },

    _redirect() {
      const params = new URLSearchParams(window.location.search);
      const next = params.get('next');
      window.location.href = (next && next.startsWith('/') && !next.startsWith('/login')) ? next : '/';
    },

    _shake(msg) {
      this.error = msg;
      this.shaking = true;
      this.password = '';
      setTimeout(() => { this.shaking = false; }, 450);
    },
  }));
});
