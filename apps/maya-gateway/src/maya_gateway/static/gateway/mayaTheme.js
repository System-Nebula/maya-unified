/** Theme bootstrap for Imagine gateway pages (mirrors dashboard mayaTheme.js storage key). */
(function () {
  const STORAGE_KEY = "maya-ui-theme";
  const DEFAULT_THEME = "unified";

  function migrateThemeId(id) {
    if (id === "gateway") return "industrial";
    if (id === "hermes") return "unified";
    return id;
  }

  function readStoredTheme() {
    try {
      const params = new URLSearchParams(window.location.search);
      const fromUrl = migrateThemeId(params.get("theme"));
      if (fromUrl === "unified" || fromUrl === "industrial" || fromUrl === "brutalist") return fromUrl;
      const stored = migrateThemeId(localStorage.getItem(STORAGE_KEY));
      if (stored === "unified" || stored === "industrial" || stored === "brutalist") return stored;
    } catch (_) {}
    return DEFAULT_THEME;
  }

  document.documentElement.dataset.mayaTheme = readStoredTheme();
  if (!document.documentElement.dataset.mvTheme) {
    document.documentElement.dataset.mvTheme = "dark";
  }
})();
