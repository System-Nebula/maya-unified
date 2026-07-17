/** Render companion / memory / settings from shared mock content. */
(function () {
  function esc(s) {
    return String(s)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }

  function fieldHtml(f) {
    if (f.type === "textarea") {
      return `<div class="field"><label>${esc(f.label)}</label><textarea rows="3">${esc(f.value)}</textarea></div>`;
    }
    if (f.type === "select") {
      const opts = (f.options || []).map((o) => `<option ${o === f.value ? "selected" : ""}>${esc(o)}</option>`).join("");
      return `<div class="field"><label>${esc(f.label)}</label><select>${opts}</select></div>`;
    }
    return `<div class="field"><label>${esc(f.label)}</label><input value="${esc(f.value)}" /></div>`;
  }

  function layoutFor(brand, tone) {
    // Brand-specific compositions while sharing the same content model.
    const presets = {
      elevenlabs: "voice-hero",
      spotify: "player-first",
      stripe: "voice-hero",
      linear: "ops-dense",
      sentry: "ops-dense",
      supabase: "ops-dense",
      raycast: "command-led",
      cursor: "command-led",
      voltagent: "terminal",
      ollama: "terminal",
      vercel: "ops-dense",
      resend: "terminal",
    };
    return presets[brand] || (tone === "warm" ? "voice-hero" : "ops-dense");
  }

  function renderCompanion(root, tone) {
    const brand = document.body.dataset.demoBrand || "";
    const layout = layoutFor(brand, tone);
    const c = MayaDemo.companion;
    const status = c.status
      .map((s) => `<span class="chip ${s.ok ? "ok" : ""}">${esc(s.label)} · ${esc(s.value)}</span>`)
      .join("");
    const msgs = c.messages
      .map(
        (m) =>
          `<div class="msg ${m.role}"><div>${esc(m.text)}</div><div class="meta">${esc(m.meta)}</div></div>`
      )
      .join("");
    const queue = c.queue
      .map(
        (t, i) =>
          `<div class="row between"><div><strong>${i === 0 ? "▶ " : ""}${esc(t.title)}</strong><div class="muted">${esc(t.artist)}</div></div><span class="muted">${esc(t.dur)}</span></div>`
      )
      .join("");
    const tools = c.tools
      .map((t) => `<div><strong>${esc(t.name)}</strong> <span>${esc(t.t)}</span> — ${esc(t.detail)}</div>`)
      .join("");
    const cmds = c.cmds.map((x) => `<span class="chip">${esc(x)}</span>`).join("");
    const imagine = c.imagine
      .map(
        (a) =>
          `<div class="panel"><div class="row between"><strong>Arena ${esc(a.label)}</strong><span class="badge-imp">${a.votes} votes</span></div><p class="muted">${esc(a.prompt)}</p></div>`
      )
      .join("");
    const extras = c.extras
      .map((e) => `<div class="panel"><h3>${esc(e.title)}</h3><p class="muted">${esc(e.body)}</p></div>`)
      .join("");

    const titles = {
      "voice-hero": ["Talk, listen, play.", "Maya stays close — voice, music, and memory without burying you in operator chrome."],
      "player-first": ["Your soundtrack, her voice.", "Player-led companion theater with cast, radio, and a living queue."],
      "ops-dense": ["Companion hub", "Live session theater: chat, voice, player, tools, vision, avatar."],
      "command-led": ["Call Maya like a command.", "Slash commands, tools, and MCP sit next to the conversation."],
      terminal: ["maya@local — companion", "Terminal-forward agent surface with tool log and voice session."],
    };
    const [htitle, hsub] = titles[layout] || titles["ops-dense"];

    const session = `
      <div class="panel">
        <div class="row between"><h2>Session</h2><div class="row">${status}</div></div>
        <div class="cta-row">
          <button class="btn" type="button">Start voice</button>
          <button class="btn ghost" type="button">Stop</button>
          <a class="btn ghost" href="./memory.html">What Maya knows</a>
          <a class="btn ghost" href="./settings.html">Tune Maya</a>
        </div>
      </div>`;
    const conversation = `
      <div class="panel">
        <h2>Conversation</h2>
        ${msgs}
        <div class="field" style="margin-top:12px"><input placeholder="Message Maya…  (/ for commands)" /></div>
      </div>`;
    const commands = `
      <div class="panel">
        <h2>Commands</h2>
        <div class="row" style="flex-wrap:wrap;gap:8px">${cmds}</div>
      </div>`;
    const player = `
      <div class="panel">
        <div class="row between"><h2>Now playing</h2><span class="chip ok">Radio</span></div>
        <div class="row" style="margin:12px 0;gap:14px">
          <div class="player-art avatar-orb" style="width:72px;height:72px;aspect-ratio:auto"></div>
          <div>
            <strong>${esc(c.queue[0].title)}</strong>
            <div class="muted">${esc(c.queue[0].artist)}</div>
          </div>
        </div>
        <div class="waveform" aria-hidden="true"></div>
        <div class="cta-row">
          <button class="btn ghost" type="button">Prev</button>
          <button class="btn" type="button">Pause</button>
          <button class="btn ghost" type="button">Skip</button>
          <button class="btn ghost" type="button">Cast Discord</button>
        </div>
        <div class="stack" style="margin-top:14px">${queue}</div>
      </div>`;
    const avatar = `
      <div class="panel">
        <h2>Avatar</h2>
        <div class="avatar-orb"></div>
        <div class="cta-row">
          <button class="btn ghost" type="button">Immersive</button>
          <button class="btn ghost" type="button">Pop-out</button>
          <button class="btn ghost" type="button">OBS</button>
        </div>
      </div>`;
    const vision = `
      <div class="panel">
        <h2>Vision &amp; Imagine</h2>
        <div class="cta-row">
          <button class="btn" type="button">Share screen</button>
          <button class="btn ghost" type="button">/imagine</button>
        </div>
        <div class="grid-2" style="margin-top:12px">${imagine}</div>
      </div>`;
    const toolPanel = `
      <div class="panel">
        <h2>Tools / MCP</h2>
        <div class="tool-log">${tools}</div>
      </div>`;
    const extraGrid = `<div class="grid-3">${extras}</div>`;

    let body;
    if (layout === "player-first") {
      body = `<div class="stack">${player}${session}<div class="grid-2">${conversation}${avatar}</div>${commands}${vision}${toolPanel}${extraGrid}</div>`;
    } else if (layout === "command-led") {
      body = `<div class="grid-2"><div class="stack">${commands}${toolPanel}${session}${conversation}</div><div class="stack">${player}${avatar}${vision}${extraGrid}</div></div>`;
    } else if (layout === "terminal") {
      body = `<div class="stack">${session}${toolPanel}<div class="grid-2">${conversation}<div class="stack">${player}${avatar}</div></div>${commands}${vision}${extraGrid}</div>`;
    } else if (layout === "voice-hero") {
      body = `<div class="grid-2"><div class="stack">${avatar}${player}${vision}</div><div class="stack">${session}${conversation}${commands}${toolPanel}</div></div>${extraGrid}`;
    } else {
      body = `<div class="grid-2"><div class="stack">${session}${conversation}${commands}</div><div class="stack">${player}${avatar}${vision}${toolPanel}</div></div>${extraGrid}`;
    }

    root.innerHTML = `
      <div class="section-title"><h1 class="hero-title">${esc(htitle)}</h1><p>${esc(hsub)}</p></div>
      ${body}
    `;
  }

  function renderMemory(root, tone) {
    const m = MayaDemo.memory;
    const facts = m.facts
      .map(
        (f) =>
          `<tr><td>${esc(f.text)}</td><td><span class="badge-imp">${f.importance}</span></td><td class="muted">${esc(f.when)}</td></tr>`
      )
      .join("");
    const skills = m.skills
      .map((s) => `<div class="panel"><h3>${esc(s.name)}</h3><p class="muted">${esc(s.desc)}</p></div>`)
      .join("");
    const approvals = m.approvals
      .map(
        (a) =>
          `<div class="row between panel" style="padding:12px"><div><strong>${esc(a.text)}</strong><div class="muted">${esc(a.source)}</div></div><div class="cta-row"><button class="btn" type="button">Approve</button><button class="btn ghost" type="button">Skip</button></div></div>`
      )
      .join("");
    const hits = m.searchHits
      .map(
        (h) =>
          `<div class="msg"><strong>${esc(h.title)}</strong><div class="muted">${esc(h.when)}</div><div>${esc(h.snippet)}</div></div>`
      )
      .join("");
    const admin = m.adminTeaser
      .map((r) => `<tr><td>${esc(r.ws)}</td><td>${esc(r.kind)}</td><td>${r.rows}</td></tr>`)
      .join("");

    const intro =
      tone === "warm"
        ? `<div class="section-title"><h1 class="hero-title">What Maya remembers</h1><p>Plain-language facts, skills, and approvals — the relationship layer behind the voice.</p></div>`
        : `<div class="section-title"><h1 class="hero-title">Memory explorer</h1><p>Profile, semantic recall, skills, approvals, conversation search, admin teaser.</p></div>`;

    const profileCard = `
      <div class="panel">
        <h2>Profile</h2>
        <p><strong>${esc(m.profile.name)}</strong></p>
        <p class="muted">${esc(m.profile.timezone)}</p>
        <p>${esc(m.profile.notes)}</p>
        <div class="cta-row">
          <button class="btn" type="button">Edit note</button>
          <a class="btn ghost" href="./settings.html">Memory prefs</a>
        </div>
      </div>`;

    const factsTable = `
      <div class="panel">
        <div class="row between"><h2>Semantic memory</h2><input placeholder="Search memories…" style="max-width:220px;background:var(--demo-bg);border:1px solid var(--demo-border);border-radius:8px;padding:8px 10px" /></div>
        <table class="table"><thead><tr><th>Fact</th><th>Imp.</th><th>When</th></tr></thead><tbody>${facts}</tbody></table>
      </div>`;

    root.innerHTML = `
      ${intro}
      <div class="grid-2">
        ${tone === "warm" ? profileCard + factsTable : factsTable + profileCard}
        <div class="stack">
          <div class="panel"><h2>Pending approvals</h2>${approvals}</div>
          <div class="panel"><h2>Conversation search</h2>${hits}</div>
        </div>
        <div class="stack">
          <h2 class="section-title" style="margin:0">Skills</h2>
          <div class="grid-2">${skills}</div>
          <div class="panel">
            <h2>Admin DB teaser</h2>
            <table class="table"><thead><tr><th>Workspace</th><th>Kind</th><th>Rows</th></tr></thead><tbody>${admin}</tbody></table>
          </div>
        </div>
      </div>
    `;
  }

  function renderSettings(root) {
    const buckets = MayaDemo.settingsBuckets;
    let activeBucket = buckets[0].id;
    let activeTab = buckets[0].tabs[0].id;

    function paint() {
      const bucket = buckets.find((b) => b.id === activeBucket) || buckets[0];
      const tab = bucket.tabs.find((t) => t.id === activeTab) || bucket.tabs[0];
      const nav = buckets
        .map(
          (b) =>
            `<button type="button" data-bucket="${b.id}" class="${b.id === activeBucket ? "is-active" : ""}">${esc(b.label)}</button>`
        )
        .join("");
      const sub = bucket.tabs
        .map(
          (t) =>
            `<button type="button" data-tab="${t.id}" class="chip ${t.id === tab.id ? "ok" : ""}" style="cursor:pointer;margin:0 6px 8px 0">${esc(t.label)}</button>`
        )
        .join("");
      const fields = tab.fields.map(fieldHtml).join("");

      root.innerHTML = `
        <div class="section-title">
          <h1 class="hero-title">Settings</h1>
          <p>Full Maya operator surface, grouped so it stays friendly. Controls are mock theater.</p>
        </div>
        <div class="side-layout">
          <aside class="panel settings-nav">${nav}</aside>
          <section class="panel">
            <div>${sub}</div>
            <h2 style="margin-top:8px">${esc(bucket.label)} · ${esc(tab.label)}</h2>
            <div style="margin-top:14px">${fields}</div>
            <div class="cta-row">
              <button class="btn" type="button">Save (demo)</button>
              <a class="btn ghost" href="./">Back to Companion</a>
              <a class="btn ghost" href="./memory.html">Open Memory</a>
            </div>
          </section>
        </div>
      `;

      root.querySelectorAll("[data-bucket]").forEach((btn) => {
        btn.addEventListener("click", () => {
          activeBucket = btn.getAttribute("data-bucket");
          const b = buckets.find((x) => x.id === activeBucket);
          activeTab = b.tabs[0].id;
          paint();
        });
      });
      root.querySelectorAll("[data-tab]").forEach((btn) => {
        btn.addEventListener("click", () => {
          activeTab = btn.getAttribute("data-tab");
          paint();
        });
      });
    }

    paint();
  }

  document.addEventListener("DOMContentLoaded", () => {
    const root = document.getElementById("demo-app");
    if (!root || !window.MayaDemo) return;
    const page = document.body.dataset.demoPage || "companion";
    const tone = document.body.classList.contains("layout-warm") ? "warm" : "dense";
    if (page === "memory") renderMemory(root, tone);
    else if (page === "settings") renderSettings(root);
    else renderCompanion(root, tone);
  });
})();
