/** Primary nav + temporary demo footer for brand sites. */
(function () {
  const DEMO_ROOT = "/dashboard/demo";

  function brandFromPath() {
    const parts = location.pathname.split("/").filter(Boolean);
    const demoIdx = parts.indexOf("demo");
    if (demoIdx >= 0 && parts[demoIdx + 1] && parts[demoIdx + 1] !== "shared" && parts[demoIdx + 1] !== "index.html") {
      return parts[demoIdx + 1];
    }
    return document.body.dataset.demoBrand || "elevenlabs";
  }

  function pageFromBody() {
    return document.body.dataset.demoPage || "companion";
  }

  function hrefFor(brand, page) {
    if (page === "companion") return `${DEMO_ROOT}/${brand}/index.html`;
    return `${DEMO_ROOT}/${brand}/${page}.html`;
  }

  function mountNav() {
    const el = document.querySelector("[data-demo-nav]");
    if (!el || !window.MayaDemo) return;
    const brand = brandFromPath();
    const page = pageFromBody();
    const meta = MayaDemo.brands.find((b) => b.slug === brand) || { label: brand };
    el.innerHTML = `
      <div class="demo-brand">Maya <span>${meta.label} demo</span></div>
      <nav class="demo-primary-nav" aria-label="Demo">
        <a href="${hrefFor(brand, "companion")}" class="${page === "companion" ? "is-active" : ""}">Companion</a>
        <a href="${hrefFor(brand, "memory")}" class="${page === "memory" ? "is-active" : ""}">Memory</a>
        <a href="${hrefFor(brand, "settings")}" class="${page === "settings" ? "is-active" : ""}">Settings</a>
      </nav>
    `;
  }

  function mountFooter() {
    const el = document.querySelector("[data-demo-footer]");
    if (!el || !window.MayaDemo) return;
    const brand = brandFromPath();
    const page = pageFromBody();
    const chips = MayaDemo.brands
      .map((b) => {
        const href = hrefFor(b.slug, page);
        return `<a href="${href}" class="${b.slug === brand ? "is-active" : ""}">${b.label}</a>`;
      })
      .join("");
    el.innerHTML = `
      <span class="label">Demo skins</span>
      ${chips}
      <a href="${DEMO_ROOT}/index.html">Hub</a>
      <a href="/dashboard/conversation.html">Live Maya</a>
    `;
  }

  document.addEventListener("DOMContentLoaded", () => {
    mountNav();
    mountFooter();
  });
})();
