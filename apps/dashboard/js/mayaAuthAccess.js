/** Shared login state — email + OAuth. */
(function () {
  const EMAIL_RE = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;
  const USERNAME_RE = /^[a-z0-9._-]{2,}$/;

  function redirectAfterAuth() {
    const params = new URLSearchParams(window.location.search);
    const next = params.get("next");
    window.location.href =
      next && next.startsWith("/") && !next.startsWith("/login") ? next : "/";
  }

  function isValidEmailOrUsername(value) {
    const v = value.trim().toLowerCase();
    if (!v) return false;
    return EMAIL_RE.test(v) || USERNAME_RE.test(v);
  }

  document.addEventListener("alpine:init", () => {
    Alpine.store("mayaAuth", {
      username: "",
      password: "",
      showPw: false,
      loading: false,
      error: "",
      shaking: false,

      get oauthAvailable() {
        return Alpine.store("mayaTheme")?.oauthAvailable || false;
      },

      async init() {
        await Alpine.store("mayaTheme")?.refreshOAuthStatus?.();
        try {
          const res = await fetch("/api/auth/me");
          if (res.ok) {
            const data = await res.json();
            if (data.authenticated) redirectAfterAuth();
          }
        } catch (_) {}
      },

      submitLabel() {
        return this.loading ? "Signing in…" : "Sign In";
      },

      async submitEmail() {
        this.error = "";
        const trimmed = this.username.trim();
        if (!isValidEmailOrUsername(trimmed)) {
          this._shake("Enter a valid email address.");
          return;
        }
        if (!this.password) {
          this._shake("Password is required.");
          return;
        }
        this.loading = true;
        try {
          const res = await fetch("/api/auth/login", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
              username: trimmed.toLowerCase(),
              password: this.password,
            }),
          });
          const data = await res.json().catch(() => ({}));
          if (!res.ok) {
            this._shake(data.detail || "Invalid email or password.");
            return;
          }
          redirectAfterAuth();
        } catch (_) {
          this._shake("Network error — could not reach server.");
        } finally {
          this.loading = false;
        }
      },

      startOAuth(provider) {
        if (provider !== "google" && provider !== "discord") return;
        if (!this.oauthAvailable) return;
        window.location.href = `/api/platform/auth/login/${encodeURIComponent(provider)}`;
      },

      _shake(msg) {
        this.error = msg;
        this.shaking = true;
        this.password = "";
        setTimeout(() => {
          this.shaking = false;
        }, 450);
      },
    });

    Alpine.data("mayaIndustrialCursor", () => ({
      on: true,
      _timer: null,
      init() {
        this._timer = setInterval(() => {
          this.on = !this.on;
        }, 530);
      },
      destroy() {
        clearInterval(this._timer);
      },
    }));
  });
})();
