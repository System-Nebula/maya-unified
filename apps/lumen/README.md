# Lumen

Cinema UI with TMDB search, concurrent provider racing, proxied HLS/MP4 playback, and watch-together.

## What’s included

- TMDB multi-search (movies + TV)
- Scraper lab backend (`lab/`) — race all sources, resolve embeds, stream proxy
- Player (`hls.js` + MP4) with source failover
- Watch party (BroadcastChannel host/guest sync)
- Local demo catalog still available offline

## Run

```bash
cd aether-clean
npm install
# ensure lab/.env has TMDB_API_KEY=...
npm run share
```

- App: `http://localhost:5173` (also bound on your LAN / Tailscale IP)
- Lab API: `http://0.0.0.0:3847` (proxied as `/api`, including WebSocket party relay)

### Share over Tailscale

1. Both of you on Tailscale
2. You run `npm run share`
3. Friend opens `http://<your-tailscale-ip>:5173`
4. Host a watch party → copy invite link → they join the same title

Watch party sync uses a WebSocket relay (`/api/party`), not BroadcastChannel.

## Flow

1. Search a title → pick a TMDB result
2. **Play** races providers and opens the player on the first stream
3. Switch sources from the player dropdown if one fails

## Env

`lab/.env`:

```
TMDB_API_KEY=your_key
```

Optional: `TMDB_READ_TOKEN`, `PORT` (default `3847`).
