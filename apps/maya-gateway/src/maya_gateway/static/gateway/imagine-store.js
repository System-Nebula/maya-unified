/** Single-writer imagine store — fed by SSE and fetch responses. */
document.addEventListener("alpine:init", () => {
  Alpine.store("imagineStore", {
    battles: new Map(),
    dirty: false,
    sseConnected: false,

    applyDelta(delta) {
      if (delta.type === "battle_upsert" || delta.type === "battle") {
        const b = delta.battle || delta;
        if (b.battle_id) {
          this.battles.set(b.battle_id, { ...this.battles.get(b.battle_id), ...b });
        }
      }
      this.dirty = !this.dirty;
    },

    get orderedBattleIds() {
      return [...this.battles.keys()];
    },
  });
});
