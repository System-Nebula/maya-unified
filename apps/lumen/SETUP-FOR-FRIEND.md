# Lumen — setup on your machine

## Needs

- Node.js 20+ ([nodejs.org](https://nodejs.org))
- Tailscale (same network as the host)
- A free [TMDB API key](https://www.themoviedb.org/settings/api)

## Install

```bash
# unzip, then:
cd cinemaya
npm install
```

`npm install` also installs `lab/` dependencies (`postinstall`).

## Config

```bash
copy lab\.env.example lab\.env
```

Edit `lab\.env` and set:

```
TMDB_API_KEY=your_real_key
```

## Run (host a shareable instance)

```bash
npm run share
```

- App: `http://localhost:5173`
- On Tailscale: `http://<your-tailscale-ip>:5173`
- Lab API (auto-proxied): port `3847`

## Join someone else’s party

1. Both on Tailscale
2. Open their link, e.g. `http://100.x.x.x:5173/watch/...?party=1&room=1234`
3. Pick a nickname → you sync to their title, provider, play/pause

Or open their home page → **Open Rooms** / **Party** → enter the 4-digit code.

## Notes

- Only the person running `npm run share` needs the lab + TMDB key for searching/racing on their box.
- Guests joining over Tailscale use the **host’s** lab through the Vite proxy — they don’t need to run the server to watch together.
- If you want to host yourself, run `npm run share` on your machine and send your Tailscale URL.
