/** Industrial auth shell — OAuth UI + invite flow (platform auth when available). */
document.addEventListener("alpine:init", () => {
  Alpine.data("mayaIndustrialAuth", () => ({
    tab: "access",
    email: "",
    waitEmail: "",
    toast: "",
    _toastTimer: null,

    get themeStore() {
      return Alpine.store("mayaTheme");
    },

    get oauthAvailable() {
      return this.themeStore?.oauthAvailable || false;
    },

    init() {
      this.themeStore?.refreshOAuthStatus?.();
    },

    isValidEmail(value) {
      return value.length > 3 && value.includes("@");
    },

    showToast(message) {
      this.toast = message;
      clearTimeout(this._toastTimer);
      this._toastTimer = setTimeout(() => {
        this.toast = "";
      }, 4200);
    },

    async startOAuth(provider) {
      if (!this.oauthAvailable) {
        this.showToast("Platform OAuth not configured");
        return;
      }
      window.location.href = `/api/platform/auth/login/${encodeURIComponent(provider)}`;
    },

    submitAccessEmail() {
      if (!this.isValidEmail(this.email)) {
        this.showToast("Enter a valid invite email");
        return;
      }
      this.showToast("Magic link flow not configured yet");
    },

    submitWaitlist() {
      if (!this.isValidEmail(this.waitEmail)) {
        this.showToast("Enter a valid email");
        return;
      }
      this.showToast("Waitlist not open");
    },
  }));

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
