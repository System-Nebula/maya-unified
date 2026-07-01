/** Imperative battle feed renderer — no x-for over collections. */
(function () {
  function escapeHtml(s) {
    return String(s)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }

  function slotHtml(slot, img, state, winner) {
    const winnerCls =
      state === "resolved" && winner === slot
        ? " arena-winner"
        : state === "resolved" && winner && winner !== "tie" && winner !== slot
          ? " arena-loser"
          : "";
    const inner = img
      ? `<img src="${escapeHtml(img)}" alt="candidate ${slot.toUpperCase()}" loading="lazy">`
      : `<div class="arena-skeleton"></div>`;
    return `
      <div class="arena-slot arena-slot-${slot}${winnerCls}">
        <div class="arena-frame">${inner}<span class="arena-label">${slot.toUpperCase()}</span></div>
      </div>`;
  }

  function revealHtml(model, rating) {
    if (!model) return "";
    const r = rating != null ? ` <span class="muted">· ${rating}</span>` : "";
    return `<div class="arena-reveal"><strong>${escapeHtml(model)}</strong>${r}</div>`;
  }

  function battleCardHtml(b) {
    const state = b.state || "generating";
    const winner = b.winner || "";
    let statusPill = "";
    if (state === "generating") statusPill = '<span class="status-pill processing">generating</span>';
    else if (state === "voting") statusPill = '<span class="status-pill processing">your vote</span>';
    else if (state === "resolved") statusPill = '<span class="status-pill completed">resolved</span>';

    let voteBlock = "";
    if (state === "voting") {
      voteBlock = `
        <div class="arena-vote">
          <button type="button" class="arena-vote-btn" data-vote="${b.battle_id}" data-choice="a">◀ A is better</button>
          <button type="button" class="arena-vote-btn arena-vote-tie" data-vote="${b.battle_id}" data-choice="tie">Tie</button>
          <button type="button" class="arena-vote-btn" data-vote="${b.battle_id}" data-choice="b">B is better ▶</button>
        </div>`;
    } else if (state === "resolved") {
      const msg =
        winner === "tie"
          ? "You called it a tie."
          : winner
            ? `Winner: ${winner.toUpperCase()}.`
            : "Battle resolved.";
      voteBlock = `<div class="arena-result">${msg}</div>`;
    }

    const revealA = state === "resolved" ? revealHtml(b.model_a, b.rating_a) : "";
    const revealB = state === "resolved" ? revealHtml(b.model_b, b.rating_b) : "";

    return `
      <div class="arena-card arena-${state}" id="battle-${escapeHtml(b.battle_id)}" data-battle-id="${escapeHtml(b.battle_id)}">
        <div class="arena-card-head">
          <span class="arena-prompt">${escapeHtml(b.prompt || "")}</span>
          ${statusPill}
        </div>
        <div class="arena-matchup">
          ${slotHtml("a", b.image_a, state, winner)}
          ${slotHtml("b", b.image_b, state, winner)}
        </div>
        ${state === "resolved" ? `<div style="display:grid;grid-template-columns:1fr 1fr;gap:0.6rem">${revealA}${revealB}</div>` : ""}
        ${voteBlock}
      </div>`;
  }

  window.GatewayFeedRenderer = {
    mount(feedEl, store) {
      const nodes = new Map();

      function redraw() {
        const ids = store.orderedBattleIds;
        const seen = new Set();
        for (const id of ids) {
          seen.add(id);
          const b = store.battles.get(id);
          if (!b) continue;
          const html = battleCardHtml(b);
          const existing = nodes.get(id);
          if (existing) {
            if (existing._state !== b.state || existing._imgA !== b.image_a || existing._imgB !== b.image_b) {
              const wrap = document.createElement("div");
              wrap.innerHTML = html;
              const newNode = wrap.firstElementChild;
              existing.el.replaceWith(newNode);
              nodes.set(id, { el: newNode, _state: b.state, _imgA: b.image_a, _imgB: b.image_b });
            }
          } else {
            const wrap = document.createElement("div");
            wrap.innerHTML = html;
            const newNode = wrap.firstElementChild;
            feedEl.appendChild(newNode);
            nodes.set(id, { el: newNode, _state: b.state, _imgA: b.image_a, _imgB: b.image_b });
          }
        }
        for (const [id, rec] of nodes) {
          if (!seen.has(id)) {
            rec.el.remove();
            nodes.delete(id);
          }
        }
        const empty = document.getElementById("imagine-empty");
        if (empty) empty.style.display = ids.length ? "none" : "flex";
      }

      Alpine.effect(() => {
        store.dirty;
        store.battles.size;
        requestAnimationFrame(redraw);
      });

      feedEl.addEventListener("click", async (e) => {
        const btn = e.target.closest("[data-vote]");
        if (!btn) return;
        const battleId = btn.dataset.vote;
        const choice = btn.dataset.choice;
        const fd = new FormData();
        fd.append("battle_id", battleId);
        fd.append("choice", choice);
        const resp = await fetch("/gateway/imagine/vote", {
          method: "POST",
          body: fd,
          headers: { Accept: "application/json" },
        });
        if (resp.ok) {
          const data = await resp.json();
          if (data.battle) store.applyDelta({ type: "battle_upsert", battle: data.battle });
          window.dispatchEvent(new CustomEvent("gateway:leaderboardRefresh"));
        }
      });

      return { redraw };
    },
  };
})();
