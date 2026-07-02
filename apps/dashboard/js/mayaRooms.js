document.addEventListener("alpine:init", () => {
  Alpine.data("mayaRooms", () => ({
    rooms: [],
    creating: false,
    error: "",
    form: { name: "", visibility: "public" },

    async init() {
      await this.load();
    },

    async load() {
      try {
        const r = await fetch("/api/rooms");
        if (!r.ok) {
          this.error = "Login required";
          return;
        }
        const d = await r.json();
        this.rooms = d.rooms || [];
      } catch (e) {
        this.error = String(e.message || e);
      }
    },

    async createRoom() {
      this.creating = true;
      this.error = "";
      try {
        const r = await fetch("/api/rooms", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(this.form),
        });
        const d = await r.json();
        if (!r.ok) throw new Error(d.detail || "Create failed");
        this.form.name = "";
        await this.load();
      } catch (e) {
        this.error = String(e.message || e);
      } finally {
        this.creating = false;
      }
    },

    copyLink(room) {
      const url = `${window.location.origin}${room.share_url}`;
      navigator.clipboard?.writeText(url);
    },

    async closeRoom(room) {
      await fetch(`/api/rooms/${room.slug}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ status: "closed" }),
      });
      await this.load();
    },
  }));
});
