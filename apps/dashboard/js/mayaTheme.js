/** Maya UI theme registry — browser-local aesthetic switching. */
(function () {
  const STORAGE_KEY = "maya-ui-theme";
  const DEFAULT_THEME = "unified";

  const THEMES = {
    unified: { id: "unified", label: "Maya Unified", description: "Default operator portal" },
    industrial: { id: "industrial", label: "Industrial", description: "Stealth terminal aesthetic" },
    brutalist: {
      id: "brutalist",
      label: "Brutalist",
      description: "Concrete mono transport — album-art player aesthetic",
    },
    "brutalist-dark": {
      id: "brutalist-dark",
      label: "Brutalist Dark",
      description: "Black concrete mono — white rules, amber signal",
    },
  };

  function migrateThemeId(id) {
    if (id === "gateway") return "industrial";
    if (id === "hermes") return "unified";
    return id;
  }

  function validTheme(id) {
    const migrated = migrateThemeId(id);
    return migrated && THEMES[migrated] ? migrated : DEFAULT_THEME;
  }

  function readStoredTheme() {
    try {
      const params = new URLSearchParams(window.location.search);
      const fromUrl = migrateThemeId(params.get("theme"));
      if (fromUrl && THEMES[fromUrl]) return fromUrl;
      return validTheme(localStorage.getItem(STORAGE_KEY));
    } catch (_) {
      return DEFAULT_THEME;
    }
  }

  function applyTheme(id) {
    const themeId = validTheme(id);
    document.documentElement.dataset.mayaTheme = themeId;
    if (!document.documentElement.dataset.mvTheme) {
      document.documentElement.dataset.mvTheme = "dark";
    }
    return themeId;
  }

  function persistTheme(id) {
    try {
      localStorage.setItem(STORAGE_KEY, validTheme(id));
    } catch (_) {}
  }

  applyTheme(readStoredTheme());

  window.mayaTheme = {
    STORAGE_KEY,
    DEFAULT_THEME,
    THEMES,
    readStoredTheme,
    applyTheme,
    persistTheme,
    init() {
      const themeId = applyTheme(readStoredTheme());
      if (window.Alpine?.store) {
        const store = Alpine.store("mayaTheme");
        if (store) store.id = themeId;
      }
    },
  };

  document.addEventListener("alpine:init", () => {
    Alpine.store("mayaTheme", {
      id: readStoredTheme(),
      themes: Object.values(THEMES),
      oauthAvailable: false,
      oauthProviders: [],
      oauthMessage: "",

      get current() {
        return THEMES[this.id] || THEMES[DEFAULT_THEME];
      },

      setTheme(id) {
        this.id = validTheme(id);
        applyTheme(this.id);
        persistTheme(this.id);
      },

      async refreshOAuthStatus() {
        try {
          const res = await fetch("/api/platform/auth/status");
          if (!res.ok) return;
          const data = await res.json();
          this.oauthAvailable = !!data.oauth_available;
          this.oauthProviders = Array.isArray(data.providers) ? data.providers : [];
          this.oauthMessage = data.message || "";
        } catch (_) {
          this.oauthAvailable = false;
          this.oauthProviders = [];
        }
      },

      init() {
        this.id = applyTheme(readStoredTheme());
        this.refreshOAuthStatus();
      },
    });

    Alpine.data("mayaThemePicker", () => ({
      get themes() {
        return Alpine.store("mayaTheme").themes;
      },
      get activeId() {
        return Alpine.store("mayaTheme").id;
      },
      pick(id) {
        Alpine.store("mayaTheme").setTheme(id);
      },
    }));
  });
})();
