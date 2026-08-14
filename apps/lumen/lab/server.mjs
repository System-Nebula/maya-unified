import http from "node:http";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { createRequire } from "node:module";
import { Readable } from "node:stream";
import { fetch as undiciFetch, Agent } from "undici";
import { WebSocketServer } from "ws";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const require = createRequire(import.meta.url);
const scrapers = require("./scrapers.js");

// pipelining:0 avoids undici H1 "assert(!this.paused)" crashes under concurrent proxy load
const insecureAgent = new Agent({
  connect: { rejectUnauthorized: false },
  pipelining: 0,
  connections: 32,
  keepAliveTimeout: 10_000,
  keepAliveMaxTimeout: 30_000,
  bodyTimeout: 120_000,
  headersTimeout: 30_000,
});
const BROWSER_UA =
  "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36";

/** undici can throw uncatchable AssertionErrors from socket 'end' — keep the lab alive */
function isBenignUndiciCrash(err) {
  if (!err) return false;
  const msg = String(err.message || err);
  return (
    err.code === "ERR_ASSERTION" &&
    (msg.includes("paused") || msg.includes("this.paused") || /client-h1/i.test(err.stack || ""))
  );
}

function isBenignStreamCancel(reason) {
  const err = reason?.cause || reason;
  const code = err?.code || reason?.code;
  const msg = String(err?.message || reason?.message || reason || "");
  return (
    code === "ERR_INVALID_STATE" &&
    /ReadableStream is locked|Invalid state/i.test(msg)
  );
}

process.on("uncaughtException", (err) => {
  if (isBenignUndiciCrash(err)) {
    return;
  }
  // Don't die on transient network/assert noise from scrapers either
  if (err && (err.code === "ECONNRESET" || err.code === "EPIPE" || err.code === "ECONNABORTED")) {
    return;
  }
  if (isBenignStreamCancel(err)) return;
  console.error("[lab] uncaughtException:", err);
  process.exit(1);
});

process.on("unhandledRejection", (reason) => {
  if (isBenignUndiciCrash(reason) || isBenignStreamCancel(reason)) return;
  console.error("[lab] unhandledRejection:", reason);
});

/** Normalize scheme-less hosts (cors.aether.mom/...) so undici/proxy don't 400. */
function normalizeFetchUrl(input) {
  const raw = String(input || "").trim();
  if (!raw) return raw;
  if (/^https?:\/\//i.test(raw)) return raw;
  if (/^\/\//.test(raw)) return `https:${raw}`;
  // host/path without scheme
  if (/^[a-z0-9][a-z0-9.-]*\.[a-z]{2,}([/:?]|$)/i.test(raw)) {
    return `https://${raw}`;
  }
  return raw;
}

async function safeFetch(url, options = {}) {
  const normalized = normalizeFetchUrl(url);
  try {
    return await undiciFetch(normalized, {
      ...options,
      dispatcher: options.dispatcher || insecureAgent,
    });
  } catch (e) {
    const detail = e.cause?.code || e.cause?.message || e.message;
    const err = new Error(`fetch failed (${detail}) for ${normalized}`);
    err.cause = e;
    throw err;
  }
}

/** Hosts the P-Stream userscript also refuses to touch. */
const FETCH_HOST_BLACKLIST = new Set(["fsharetv.co", "lmscript.xyz"]);

function isBlacklistedHost(targetUrl) {
  try {
    const host = new URL(normalizeFetchUrl(targetUrl)).hostname.toLowerCase();
    if (FETCH_HOST_BLACKLIST.has(host)) return true;
    for (const blocked of FETCH_HOST_BLACKLIST) {
      if (host.endsWith(`.${blocked}`)) return true;
    }
  } catch {
    return true;
  }
  return false;
}

function makeFullUrl(url, ops = {}) {
  let left = ops.baseUrl ?? "";
  let right = String(url || "");
  if (left && !left.endsWith("/")) left += "/";
  if (right.startsWith("/")) right = right.slice(1);
  let full = left + right;
  if (!/^https?:\/\//i.test(full) && !/^\/\//.test(full)) {
    if (/^[a-z0-9][a-z0-9.-]*\.[a-z]{2,}/i.test(full)) full = `https://${full}`;
    else throw new Error(`Invalid URL: ${full}`);
  }
  full = normalizeFetchUrl(full);
  const parsed = new URL(full);
  for (const [k, v] of Object.entries(ops.query || {})) {
    if (v != null) parsed.searchParams.set(k, String(v));
  }
  return parsed.toString();
}

async function handleApiFetch(req, res) {
  const body = await readBody(req);
  if (!body?.url && !body?.baseUrl) {
    return json(res, 400, { error: "url required" });
  }
  let target;
  try {
    target = makeFullUrl(body.url || "", {
      baseUrl: body.baseUrl,
      query: body.query,
    });
  } catch (e) {
    return json(res, 400, { error: e.message || "invalid url" });
  }
  if (isBlacklistedHost(target)) {
    return json(res, 403, { error: `Request blocked: blacklisted host` });
  }

  const method = String(body.method || "GET").toUpperCase();
  const headers = { "User-Agent": BROWSER_UA, ...(body.headers || {}) };
  let payload = body.body;
  if (
    payload &&
    typeof payload === "object" &&
    !(payload instanceof URLSearchParams) &&
    !(Buffer.isBuffer(payload))
  ) {
    if (!headers["Content-Type"] && !headers["content-type"]) {
      headers["Content-Type"] = "application/json";
    }
    payload = JSON.stringify(payload);
  }

  let upstream;
  try {
    upstream = await safeFetch(target, {
      method,
      headers,
      body: method === "GET" || method === "HEAD" ? undefined : payload,
      redirect: "follow",
    });
  } catch (e) {
    return json(res, 502, {
      error: e.message || "upstream fetch failed",
      statusCode: 0,
      headers: {},
      finalUrl: target,
      body: null,
    });
  }

  const contentType = upstream.headers.get("content-type") || "";
  const text = await upstream.text();
  let parsed = text;
  if (contentType.includes("application/json") || /^[\[{]/.test(text.trim())) {
    try {
      parsed = JSON.parse(text);
    } catch {
      parsed = text;
    }
  }

  json(res, 200, {
    success: true,
    response: {
      statusCode: upstream.status,
      headers: Object.fromEntries(upstream.headers.entries()),
      finalUrl: upstream.url || target,
      body: parsed,
    },
  });
}

function cancelBody(body) {
  try {
    const result = body?.cancel?.();
    // cancel() returns a Promise — rejection must not become unhandledRejection
    if (result && typeof result.then === "function") {
      result.catch(() => {});
    }
  } catch {
    /* ignore locked/cancelled streams */
  }
}

function loadEnvFiles() {
  for (const name of [".env", ".env.local"]) {
    const file = path.join(__dirname, name);
    if (!fs.existsSync(file)) continue;
    for (const line of fs.readFileSync(file, "utf8").split(/\r?\n/)) {
      if (!line || line.trim().startsWith("#")) continue;
      const eq = line.indexOf("=");
      if (eq < 1) continue;
      const key = line.slice(0, eq).trim();
      let value = line.slice(eq + 1).trim();
      if (
        (value.startsWith('"') && value.endsWith('"')) ||
        (value.startsWith("'") && value.endsWith("'"))
      ) {
        value = value.slice(1, -1);
      }
      if (!(key in process.env)) process.env[key] = value;
    }
  }
}

loadEnvFiles();

const PORT = Number(process.env.PORT) || 3847;
const TMDB_KEY = process.env.TMDB_API_KEY || "";
const TMDB_TOKEN = process.env.TMDB_READ_TOKEN || "";
const publicDir = path.join(__dirname, "public");
const partyRooms = new Map(); // code -> Set<WebSocket>
const partyRoomMeta = new Map(); // code -> { contentId, title, hostName, updatedAt }
const FEATURES = { requires: [], disallowed: [] };
const QUALITY_ORDER = ["4k", "2160", "1440", "1080", "720", "480", "360", "unknown"];

function createHttpFetcher() {
  const full = async (url, options = {}) => {
    let target = url;
    if (options.baseUrl) {
      target = new URL(
        url.replace(/^\//, ""),
        options.baseUrl.endsWith("/") ? options.baseUrl : options.baseUrl + "/",
      ).toString();
    }
    if (options.query && Object.keys(options.query).length) {
      const u = new URL(target);
      for (const [k, v] of Object.entries(options.query)) {
        if (v != null) u.searchParams.set(k, String(v));
      }
      target = u.toString();
    }

    const method = (options.method || "GET").toUpperCase();
    const headers = {
      "User-Agent": BROWSER_UA,
      ...defaultHeadersForUrl(target),
      ...(options.headers || {}),
    };
    let body = options.body;
    if (
      body &&
      typeof body === "object" &&
      !(body instanceof URLSearchParams) &&
      !(body instanceof Buffer)
    ) {
      if (!headers["Content-Type"] && !headers["content-type"]) {
        headers["Content-Type"] = "application/json";
      }
      body = JSON.stringify(body);
    }

    const res = await safeFetch(target, {
      method,
      headers,
      body: method === "GET" || method === "HEAD" ? undefined : body,
      redirect: "follow",
    });

    const contentType = res.headers.get("content-type") || "";
    let parsed;
    // Always fully consume the body so undici doesn't pause the H1 parser
    let text;
    try {
      text = await res.text();
    } catch (e) {
      cancelBody(res.body);
      throw new Error(`fetch body failed (${e.message}) for ${target}`);
    }
    if (contentType.includes("application/json") || /^[\[{]/.test(text.trim())) {
      try {
        parsed = JSON.parse(text);
      } catch {
        parsed = text;
      }
    } else {
      parsed = text;
    }

    return {
      body: parsed,
      statusCode: res.status,
      headers: Object.fromEntries(res.headers.entries()),
      finalUrl: res.url,
    };
  };

  const fetcher = async (url, options) => (await full(url, options)).body;
  fetcher.full = full;
  return scrapers.normalizeFetcher(fetcher);
}

function json(res, status, data) {
  const body = JSON.stringify(data);
  res.writeHead(status, {
    "Content-Type": "application/json; charset=utf-8",
    "Cache-Control": "no-store",
  });
  res.end(body);
}

function readBody(req) {
  return new Promise((resolve, reject) => {
    const chunks = [];
    req.on("data", (c) => chunks.push(c));
    req.on("end", () => {
      const raw = Buffer.concat(chunks).toString("utf8");
      if (!raw) return resolve({});
      try {
        resolve(JSON.parse(raw));
      } catch (e) {
        reject(e);
      }
    });
    req.on("error", reject);
  });
}

function buildMedia(input) {
  const type = input.type === "show" ? "show" : "movie";
  const media = {
    type,
    tmdbId: String(input.tmdbId || "").trim(),
    title: String(input.title || "Unknown").trim(),
    releaseYear: Number(input.releaseYear) || undefined,
    imdbId: input.imdbId ? String(input.imdbId).trim() : undefined,
  };
  if (!media.tmdbId) throw new Error("tmdbId is required");
  if (type === "show") {
    media.season = { number: Number(input.season) || 1 };
    media.episode = { number: Number(input.episode) || 1 };
  }
  return media;
}

function tmdbHeaders() {
  const headers = { Accept: "application/json" };
  if (TMDB_TOKEN) headers.Authorization = `Bearer ${TMDB_TOKEN}`;
  return headers;
}

function detectIsAnime(item) {
  const originalLanguage = item?.original_language || item?.originalLanguage || null;
  const genreNames = (item?.genres || []).map((g) =>
    String(typeof g === "string" ? g : g?.name || "").toLowerCase(),
  );
  const keywordIds = [
    ...((item?.keywords && item.keywords.keywords) || []),
    ...((item?.keywords && item.keywords.results) || []),
    ...((item?.keywordIds) || []),
  ].map((k) => String(typeof k === "object" && k ? k.id : k));
  const ANIME_KEYWORD = "210024";
  return Boolean(
    keywordIds.includes(ANIME_KEYWORD) ||
      (originalLanguage === "ja" && genreNames.some((g) => g.includes("animation"))),
  );
}

const malIdCache = new Map();

function normalizeAnimeTitle(title) {
  return String(title || "")
    .toLowerCase()
    .normalize("NFKD")
    .replace(/[\u0300-\u036f]/g, "")
    .replace(/[^a-z0-9]+/g, " ")
    .trim();
}

/** Resolve MyAnimeList id via AniList for AniSkip (e.g. One Piece → 21). */
async function resolveMalIdFromAniList(title, year) {
  const key = `${normalizeAnimeTitle(title)}|${year || ""}`;
  if (malIdCache.has(key)) return malIdCache.get(key);
  const want = normalizeAnimeTitle(title);
  if (!want) {
    malIdCache.set(key, 0);
    return 0;
  }
  try {
    const res = await safeFetch("https://graphql.anilist.co", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        Accept: "application/json",
        "User-Agent": BROWSER_UA,
      },
      body: JSON.stringify({
        query: `query ($search: String) {
          Page(page: 1, perPage: 12) {
            media(search: $search, type: ANIME, sort: POPULARITY_DESC) {
              idMal
              seasonYear
              title { romaji english native }
            }
          }
        }`,
        variables: { search: title },
      }),
    });
    if (!res.ok) {
      cancelBody(res.body);
      malIdCache.set(key, 0);
      return 0;
    }
    const data = await res.json();
    const list = data?.data?.Page?.media || [];
    let best = null;
    for (const item of list) {
      const names = [item.title?.romaji, item.title?.english, item.title?.native]
        .filter(Boolean)
        .map(normalizeAnimeTitle);
      let score = 0;
      for (const n of names) {
        if (n === want) score = Math.max(score, 100);
        else if (n.includes(want) || want.includes(n)) score = Math.max(score, 70);
      }
      if (year && item.seasonYear) {
        const dy = Math.abs(Number(item.seasonYear) - Number(year));
        if (dy === 0) score += 15;
        else if (dy <= 1) score += 5;
      }
      if (!best || score > best.score) best = { score, idMal: Number(item.idMal) || 0 };
    }
    const malId = best && best.score >= 70 ? best.idMal : 0;
    malIdCache.set(key, malId);
    return malId;
  } catch {
    malIdCache.set(key, 0);
    return 0;
  }
}

async function enrichMedia(media) {
  if (!TMDB_KEY && !TMDB_TOKEN) return media;
  const kind = media.type === "show" ? "tv" : "movie";
  try {
    if (!media.imdbId) {
      const extUrl = new URL(`https://api.themoviedb.org/3/${kind}/${media.tmdbId}/external_ids`);
      if (!TMDB_TOKEN) extUrl.searchParams.set("api_key", TMDB_KEY);
      const extRes = await fetch(extUrl, { headers: tmdbHeaders() });
      if (extRes.ok) {
        const ext = await extRes.json();
        if (ext.imdb_id) media.imdbId = String(ext.imdb_id);
      }
    }
  } catch {
    /* keep media without imdb */
  }

  // Detect anime so we don't race HiAnime/Anisurge against Western shows.
  try {
    const detailUrl = new URL(`https://api.themoviedb.org/3/${kind}/${media.tmdbId}`);
    detailUrl.searchParams.set("append_to_response", "keywords");
    if (!TMDB_TOKEN) detailUrl.searchParams.set("api_key", TMDB_KEY);
    const detailRes = await fetch(detailUrl, { headers: tmdbHeaders() });
    if (detailRes.ok) {
      const data = await detailRes.json();
      media.originalLanguage = data.original_language || media.originalLanguage || null;
      media.isAnime = detectIsAnime(data);
    }
  } catch {
    /* leave isAnime unset → treat as non-anime (safer) */
  }
  if (media.isAnime == null) media.isAnime = false;
  return media;
}

function mapSubtitleHit(raw, source) {
  const language =
    raw.language ||
    raw.lang ||
    raw.attributes?.language ||
    raw.ISO639 ||
    null;
  const url =
    raw.url ||
    raw.downloadUrl ||
    raw.download_url ||
    raw.SubDownloadLink ||
    null;
  const format = String(raw.format || raw.encoding || raw.type || "srt").toLowerCase();
  if (!url && !raw.fileId && !raw.attributes?.files?.[0]?.file_id) return null;
  return {
    id: String(
      raw.id ||
        raw.SubFileID ||
        raw.fileId ||
        `${source}-${language}-${url || raw.fileId || Math.random()}`,
    ),
    language: language ? String(language).toLowerCase().slice(0, 8) : "unknown",
    url: url ? String(url) : null,
    fileId: raw.fileId || raw.attributes?.files?.[0]?.file_id || null,
    type: format.includes("vtt") ? "vtt" : format.includes("ass") ? "ass" : "srt",
    label: raw.display || raw.releaseName || raw.MovieReleaseName || raw.fileName || null,
    source,
    hearingImpaired: Boolean(raw.hearingImpaired || raw.HearingImpaired || raw.hi),
  };
}

function isEnglishSubtitleLanguage(code) {
  const value = String(code || "")
    .trim()
    .toLowerCase()
    .split(/[-_]/)[0];
  return value === "en" || value === "eng" || value === "english";
}

async function searchWyzieSubtitles({ imdbId, tmdbId, season, episode }) {
  const key =
    process.env.WYZIE_API_KEY ||
    process.env.WYZIE_KEY ||
    process.env.WYSIE_API_KEY ||
    process.env.WYSIE_KEY ||
    "";
  if (!key) return { results: [], skipped: "no_key" };
  const id = imdbId || tmdbId;
  if (!id) return { results: [], skipped: "no_id" };
  const language = (process.env.SUBTITLE_LANGUAGE || "en").trim().toLowerCase() || "en";
  const url = new URL("https://sub.wyzie.io/search");
  url.searchParams.set("id", String(id));
  url.searchParams.set("key", key);
  url.searchParams.set("language", language);
  if (season) url.searchParams.set("season", String(season));
  if (episode) url.searchParams.set("episode", String(episode));
  const res = await safeFetch(url.toString(), {
    headers: { Accept: "application/json", "User-Agent": BROWSER_UA },
  });
  const text = await res.text();
  if (!res.ok) throw new Error(`Wyzie ${res.status}: ${text.slice(0, 120)}`);
  let data;
  try {
    data = JSON.parse(text);
  } catch {
    return { results: [] };
  }
  const list = Array.isArray(data) ? data : data.subtitles || data.results || [];
  return {
    results: list
      .map((item) => mapSubtitleHit(item, "opensubs"))
      .filter((item) => item && isEnglishSubtitleLanguage(item.language)),
  };
}

async function searchOpenSubtitlesApi({ imdbId, tmdbId, type, season, episode }) {
  const key = process.env.OPENSUBTITLES_API_KEY || "";
  if (!key) return { results: [], skipped: "no_key" };
  const language = (process.env.SUBTITLE_LANGUAGE || "en").trim().toLowerCase() || "en";
  const url = new URL("https://api.opensubtitles.com/api/v1/subtitles");
  if (imdbId) url.searchParams.set("imdb_id", String(imdbId).replace(/^tt/i, ""));
  else if (tmdbId) url.searchParams.set("tmdb_id", String(tmdbId));
  if (type === "show") {
    url.searchParams.set("type", "episode");
    if (season) url.searchParams.set("season_number", String(season));
    if (episode) url.searchParams.set("episode_number", String(episode));
  } else {
    url.searchParams.set("type", "movie");
  }
  url.searchParams.set("languages", language);
  url.searchParams.set("order_by", "download_count");
  url.searchParams.set("order_direction", "desc");
  const res = await safeFetch(url.toString(), {
    headers: {
      Accept: "application/json",
      "User-Agent": "CINEMAYA v1.0",
      "Api-Key": key,
    },
  });
  const text = await res.text();
  if (!res.ok) throw new Error(`OpenSubtitles ${res.status}: ${text.slice(0, 120)}`);
  let data;
  try {
    data = JSON.parse(text);
  } catch {
    return { results: [] };
  }
  const list = Array.isArray(data.data) ? data.data : [];
  return {
    results: list
      .map((item) =>
        mapSubtitleHit(
          {
            id: item.id,
            language: item.attributes?.language,
            fileId: item.attributes?.files?.[0]?.file_id,
            format: item.attributes?.files?.[0]?.file_name || "srt",
            releaseName: item.attributes?.release || item.attributes?.feature_details?.title,
            hearingImpaired: item.attributes?.hearing_impaired,
            attributes: item.attributes,
          },
          "opensubs",
        ),
      )
      .filter((item) => item && isEnglishSubtitleLanguage(item.language)),
  };
}

async function resolveOpenSubtitlesDownload(fileId) {
  const key = process.env.OPENSUBTITLES_API_KEY || "";
  if (!key || !fileId) return null;
  const res = await safeFetch("https://api.opensubtitles.com/api/v1/download", {
    method: "POST",
    headers: {
      Accept: "application/json",
      "Content-Type": "application/json",
      "User-Agent": "CINEMAYA v1.0",
      "Api-Key": key,
    },
    body: JSON.stringify({ file_id: Number(fileId) }),
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.message || `download failed (${res.status})`);
  return data.link || null;
}

async function handleSubtitlesSearch(_req, res, url) {
  const tmdbId = (url.searchParams.get("tmdbId") || url.searchParams.get("id") || "").trim();
  const type = url.searchParams.get("type") === "show" ? "show" : "movie";
  const season = Number(url.searchParams.get("season") || 0) || undefined;
  const episode = Number(url.searchParams.get("episode") || 0) || undefined;
  if (!tmdbId) return json(res, 400, { error: "tmdbId required" });

  let imdbId = (url.searchParams.get("imdbId") || "").trim() || undefined;
  try {
    const enriched = await enrichMedia({ type, tmdbId, title: "x", imdbId });
    imdbId = enriched.imdbId || imdbId;
  } catch {
    /* ignore */
  }

  const sources = [];
  const results = [];

  try {
    const wyzie = await searchWyzieSubtitles({ imdbId, tmdbId, season, episode });
    if (wyzie.skipped) sources.push({ id: "wyzie", status: "skipped", reason: wyzie.skipped });
    else {
      sources.push({ id: "wyzie", status: "ok", count: wyzie.results.length });
      results.push(...wyzie.results);
    }
  } catch (e) {
    sources.push({ id: "wyzie", status: "error", reason: e.message });
  }

  try {
    const oss = await searchOpenSubtitlesApi({ imdbId, tmdbId, type, season, episode });
    if (oss.skipped) {
      sources.push({ id: "opensubtitles", status: "skipped", reason: oss.skipped });
    } else {
      sources.push({ id: "opensubtitles", status: "ok", count: oss.results.length });
      results.push(...oss.results);
    }
  } catch (e) {
    sources.push({ id: "opensubtitles", status: "error", reason: e.message });
  }

  const seen = new Set();
  const unique = [];
  for (const item of results) {
    if (!isEnglishSubtitleLanguage(item.language)) continue;
    const key = `${item.language}|${item.url || ""}|${item.fileId || ""}`;
    if (seen.has(key)) continue;
    seen.add(key);
    unique.push(item);
  }

  unique.sort((a, b) => String(a.label || "").localeCompare(String(b.label || "")));

  json(res, 200, {
    tmdbId,
    imdbId: imdbId || null,
    type,
    season: season || null,
    episode: episode || null,
    results: unique.slice(0, 20),
    sources,
    hint:
      unique.length === 0
        ? "Set WYZIE_API_KEY or OPENSUBTITLES_API_KEY in lab/.env for external subtitles"
        : null,
  });
}

function mapTmdbListItem(item, type) {
  return {
    tmdbId: String(item.id),
    type,
    title: item.title || item.name,
    releaseYear:
      Number((item.release_date || item.first_air_date || "").slice(0, 4)) || null,
    overview: item.overview || "",
    originalLanguage: item.original_language || null,
    poster: item.poster_path
      ? `https://image.tmdb.org/t/p/w500${item.poster_path}`
      : null,
    backdrop: item.backdrop_path
      ? `https://image.tmdb.org/t/p/w1280${item.backdrop_path}`
      : null,
  };
}

async function tmdbSearch(query) {
  if (!TMDB_KEY && !TMDB_TOKEN) {
    return {
      results: [],
      error: "Set TMDB_API_KEY in scrapers-and-lookups/.env to search by title.",
    };
  }
  const url = new URL("https://api.themoviedb.org/3/search/multi");
  url.searchParams.set("query", query);
  url.searchParams.set("include_adult", "false");
  if (!TMDB_TOKEN) url.searchParams.set("api_key", TMDB_KEY);
  const res = await fetch(url, { headers: tmdbHeaders() });
  if (!res.ok) throw new Error(`TMDB search failed: ${res.status}`);
  const data = await res.json();
  const results = (data.results || [])
    .filter((item) => item.media_type === "movie" || item.media_type === "tv")
    .slice(0, 16)
    .map((item) => {
      const isShow = item.media_type === "tv";
      return {
        tmdbId: String(item.id),
        type: isShow ? "show" : "movie",
        title: item.title || item.name,
        releaseYear:
          Number((item.release_date || item.first_air_date || "").slice(0, 4)) ||
          null,
        overview: item.overview || "",
        originalLanguage: item.original_language || null,
        poster: item.poster_path
          ? `https://image.tmdb.org/t/p/w185${item.poster_path}`
          : null,
      };
    });
  return { results };
}

function isAnimeOnlySource(providerId) {
  return /hianime|animepahe|anizone|zunime|animetsu|anisurge|anokoto|anivexa|scraper-anime|animegg|animeheaven|anineko|anitaku|2dhive|mkissa|^scraper-suzu$/i.test(
    String(providerId || ""),
  );
}

function candidateSources(media, includeDisabled) {
  return scrapers.registeredSources
    .filter((s) => includeDisabled || !s.disabled)
    .filter((s) =>
      media.type === "movie" ? Boolean(s.scrapeMovie) : Boolean(s.scrapeShow),
    )
    .filter((s) => {
      // Never race anime scrapers for non-anime titles (e.g. House of the Dragon).
      if (!media.isAnime && isAnimeOnlySource(s.id)) return false;
      return true;
    })
    .sort((a, b) => {
      if (Boolean(a.disabled) !== Boolean(b.disabled)) {
        return a.disabled ? 1 : -1;
      }
      return b.rank - a.rank;
    });
}

function mergeHeaders(stream) {
  return {
    ...(stream.preferredHeaders || {}),
    ...(stream.headers || {}),
  };
}

function looksLikeHlsUrl(url) {
  return /\.m3u8(\?|$)/i.test(String(url || ""));
}

function extractPlayable(stream) {
  if (!stream) return null;
  const headers = mergeHeaders(stream);
  if (stream.type === "hls" && stream.playlist) {
    return {
      type: "hls",
      url: stream.playlist,
      headers,
      captions: stream.captions || [],
    };
  }
  if (stream.type === "file" && stream.qualities) {
    const entries = Object.entries(stream.qualities).filter(([, q]) => q?.url);
    entries.sort((a, b) => {
      const ai = QUALITY_ORDER.indexOf(String(a[0]));
      const bi = QUALITY_ORDER.indexOf(String(b[0]));
      return (ai === -1 ? 99 : ai) - (bi === -1 ? 99 : bi);
    });
    if (!entries.length) return null;
    const [quality, file] = entries[0];
    // Anime scrapers often label HLS masters as file/mp4 ("Auto", "HD-1").
    if (file.type === "hls" || looksLikeHlsUrl(file.url)) {
      return {
        type: "hls",
        url: file.url,
        quality: String(quality),
        headers,
        captions: stream.captions || [],
      };
    }
    return {
      type: file.type === "mp4" || /\.mp4(\?|$)/i.test(file.url) ? "mp4" : "file",
      url: file.url,
      quality: String(quality),
      headers,
      captions: stream.captions || [],
    };
  }
  return null;
}

function encodeProxyPayload(url, headers = {}) {
  return Buffer.from(JSON.stringify({ url, headers })).toString("base64url");
}

function decodeProxyPayload(raw) {
  return JSON.parse(Buffer.from(raw, "base64url").toString("utf8"));
}

/** Relative so Tailscale guests hit Vite (:5173) → lab, not the host's 127.0.0.1. */
function proxyPath(targetUrl, headers = {}) {
  return `/api/proxy?p=${encodeProxyPayload(targetUrl, headers)}`;
}

/** Hotlink-guarded CDNs / APIs that 403 without an Aether Referer. */
function defaultHeadersForUrl(targetUrl) {
  try {
    const host = new URL(targetUrl).hostname.toLowerCase();
    if (
      host.endsWith(".aether.bar") ||
      host === "aether.bar" ||
      host.endsWith(".aether.cx") ||
      host === "aether.cx"
    ) {
      return {
        Referer: "https://play.aether.bar/",
        Origin: "https://play.aether.bar",
      };
    }
    if (host.endsWith(".aether.mom") || host === "aether.mom") {
      return {
        Referer: "https://aether.mom/",
        Origin: "https://aether.mom",
      };
    }
    if (host === "player.zilla-networks.com" || host.endsWith(".zilla-networks.com")) {
      return {
        Referer: "https://player.zilla-networks.com/",
        Origin: "https://player.zilla-networks.com",
      };
    }
  } catch {
    /* ignore */
  }
  return {};
}

function toProxiedPlayable(playable) {
  if (!playable?.url) return null;
  const streamUrl = normalizeFetchUrl(playable.url);
  if (!/^https?:\/\//i.test(streamUrl)) return null;
  const headers = {
    ...defaultHeadersForUrl(streamUrl),
    ...(playable.headers || {}),
  };
  const needsProxy =
    Object.keys(headers).length > 0 ||
    !/^https?:\/\/(localhost|127\.0\.0\.1)(:\d+)?\//i.test(streamUrl);
  const captions = Array.isArray(playable.captions)
    ? playable.captions
        .filter((c) => c && c.url)
        .map((c) => {
          const capUrl = normalizeFetchUrl(String(c.url));
          if (!/^https?:\/\//i.test(capUrl)) return null;
          const capNeedsProxy =
            Object.keys(headers).length > 0 ||
            !/^https?:\/\/(localhost|127\.0\.0\.1)(:\d+)?\//i.test(capUrl);
          return {
            id: c.id || capUrl,
            url: capNeedsProxy ? proxyPath(capUrl, headers) : capUrl,
            originalUrl: capUrl,
            type: c.type || "vtt",
            language: c.language || null,
            hasCorsRestrictions: Boolean(c.hasCorsRestrictions),
          };
        })
        .filter(Boolean)
    : [];
  return {
    ...playable,
    originalUrl: streamUrl,
    url: needsProxy ? proxyPath(streamUrl, headers) : streamUrl,
    proxied: needsProxy,
    captions,
  };
}

async function mapPool(items, concurrency, worker) {
  const results = new Array(items.length);
  let index = 0;
  async function run() {
    while (index < items.length) {
      const i = index++;
      results[i] = await worker(items[i], i);
    }
  }
  await Promise.all(
    Array.from({ length: Math.min(concurrency, Math.max(items.length, 1)) }, () =>
      run(),
    ),
  );
  return results;
}

/** Highest height from a master playlist (`RESOLUTION=WxH`), or null. */
function qualityFromHlsPlaylist(text) {
  if (!text || typeof text !== "string") return null;
  let maxH = 0;
  for (const m of text.matchAll(/RESOLUTION\s*=\s*(\d+)\s*x\s*(\d+)/gi)) {
    const h = Number(m[2]) || 0;
    if (h > maxH) maxH = h;
  }
  if (!maxH) {
    for (const m of text.matchAll(/\bNAME\s*=\s*"([^"]+)"/gi)) {
      const name = m[1] || "";
      const hit = name.match(/\b(\d{3,4})p?\b/i);
      const h = hit ? Number(hit[1]) : 0;
      if (h >= 240 && h <= 4320 && h > maxH) maxH = h;
    }
  }
  return maxH > 0 ? String(maxH) : null;
}

async function validateUpstreamPlayable(playable) {
  const url = playable?.url;
  if (!url || !/^https?:\/\//i.test(url)) return false;
  if (/\/video\/error(\?|$)/i.test(url)) return false;
  const wantsPlaylistGuess =
    playable.type === "hls" || /\.m3u8(\?|$)/i.test(url);
  const ac = new AbortController();
  const timer = setTimeout(() => ac.abort(), 4500);
  try {
    const headers = {
      "User-Agent": BROWSER_UA,
      ...defaultHeadersForUrl(url),
      ...(playable.headers || {}),
    };
    // HLS masters need enough bytes for all #EXT-X-STREAM-INF lines.
    if (!wantsPlaylistGuess) {
      headers.Range = "bytes=0-2048";
    }
    const res = await safeFetch(url, {
      headers,
      redirect: "follow",
      signal: ac.signal,
    });
    if (!(res.ok || res.status === 206)) {
      cancelBody(res.body);
      return false;
    }
    const ct = res.headers.get("content-type") || "";
    const wantsPlaylist =
      wantsPlaylistGuess ||
      /mpegurl|m3u8/i.test(ct) ||
      /\.m3u8(\?|$)/i.test(url);
    if (wantsPlaylist) {
      const text = await res.text();
      if (!/#EXTM3U/i.test(text)) return false;
      if (!playable.quality) {
        const q = qualityFromHlsPlaylist(text);
        if (q) playable.quality = q;
      }
      return true;
    }
    cancelBody(res.body);
    return true;
  } catch {
    return false;
  } finally {
    clearTimeout(timer);
  }
}

async function resolveEmbedToPlayable(embed, fetcher, features) {
  const provider = scrapers.registeredEmbeds.find(
    (item) => item.id === embed.embedId && !item.disabled,
  );
  if (!provider) return null;
  try {
    const output = await provider.scrape({
      url: embed.url,
      fetcher,
      proxiedFetcher: fetcher,
      features,
      progress() {},
    });
    for (const stream of output?.stream || []) {
      const playable = extractPlayable(stream);
      if (playable) {
        return { playable, embedId: provider.id, embedName: provider.name };
      }
    }
  } catch {
    return null;
  }
  return null;
}

function sleepMs(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

async function probeProviderOnce(provider, media, fetcher, features, _host, resolveEmbeds) {
  const t0 = Date.now();
  const ctx = {
    media,
    fetcher,
    proxiedFetcher: fetcher,
    features,
    progress() {},
  };
  try {
    const output =
      media.type === "movie"
        ? await provider.scrapeMovie(ctx)
        : await provider.scrapeShow(ctx);
    const streams = (output?.stream || []).filter(Boolean);
    const embeds = (output?.embeds || []).filter(Boolean);

    const playables = [];
    for (const stream of streams) {
      const playable = extractPlayable(stream);
      if (!playable) continue;
      if (!(await validateUpstreamPlayable(playable))) continue;
      const proxied = toProxiedPlayable(playable);
      if (proxied) {
        playables.push({
          sourceId: provider.id,
          sourceName: provider.name,
          embedId: stream.displayId || stream.id || null,
          embedName: stream.displayName || stream.title || null,
          playable: proxied,
        });
      }
    }

    if (resolveEmbeds && !playables.length && embeds.length) {
      // Anime / multi-embed sources — try more servers before giving up.
      const embedLimit = /hianime|animetsu|zunime|anime|xpass|xprime|anisurge|anokoto|anivexa|scraper-/i.test(provider.id)
        ? 8
        : 4;
      const embedHits = await mapPool(embeds.slice(0, embedLimit), 3, async (embed) =>
        resolveEmbedToPlayable(embed, fetcher, features),
      );
      for (const hit of embedHits.filter(Boolean)) {
        if (!(await validateUpstreamPlayable(hit.playable))) continue;
        const proxied = toProxiedPlayable(hit.playable);
        if (!proxied) continue;
        playables.push({
          sourceId: provider.id,
          sourceName: provider.name,
          embedId: hit.embedId,
          embedName: hit.embedName,
          playable: proxied,
        });
      }
    }

    const found = playables.length > 0 || embeds.length > 0;
    return {
      id: provider.id,
      name: provider.name,
      rank: provider.rank,
      disabled: Boolean(provider.disabled),
      status: playables.length ? "found" : embeds.length ? "embeds-only" : found ? "empty" : "empty",
      ms: Date.now() - t0,
      streams: streams.length,
      embeds: embeds.length,
      playables,
      message: null,
    };
  } catch (e) {
    return {
      id: provider.id,
      name: provider.name,
      rank: provider.rank,
      disabled: Boolean(provider.disabled),
      status: e instanceof scrapers.ScraperError ? "notfound" : "error",
      ms: Date.now() - t0,
      streams: 0,
      embeds: 0,
      playables: [],
      message: e.message || String(e),
    };
  }
}

/** One quick retry on transient scraper/network errors (not hard notfound). */
async function probeProvider(provider, media, fetcher, features, host, resolveEmbeds) {
  let result = await probeProviderOnce(
    provider,
    media,
    fetcher,
    features,
    host,
    resolveEmbeds,
  );
  if (result.playables.length || result.status !== "error") {
    return result;
  }
  await sleepMs(250);
  const retry = await probeProviderOnce(
    provider,
    media,
    fetcher,
    features,
    host,
    resolveEmbeds,
  );
  return retry.playables.length || retry.status !== "error" ? retry : result;
}

function rewriteM3u8(body, baseUrl, headers) {
  return body
    .split(/\r?\n/)
    .map((line) => {
      const trimmed = line.trim();
      if (!trimmed) return line;
      if (trimmed.startsWith("#")) {
        // Rewrite URI= on KEY/MAP/MEDIA (subs/audio) and any other tag attrs
        return line.replace(/URI="([^"]+)"/gi, (_, uri) => {
          try {
            const absolute = new URL(uri, baseUrl).toString();
            return `URI="${proxyPath(absolute, headers)}"`;
          } catch {
            return `URI="${uri}"`;
          }
        });
      }
      try {
        const absolute = new URL(trimmed, baseUrl).toString();
        return proxyPath(absolute, headers);
      } catch {
        return line;
      }
    })
    .join("\n");
}

function normalizeProxyHeaders(input = {}) {
  const headers = { "User-Agent": BROWSER_UA };
  for (const [key, value] of Object.entries(input)) {
    if (value == null || value === "") continue;
    const lower = key.toLowerCase();
    if (lower === "referer") headers.Referer = String(value);
    else if (lower === "origin") headers.Origin = String(value);
    else if (lower === "user-agent") headers["User-Agent"] = String(value);
    else headers[key] = String(value);
  }
  return headers;
}

async function handleProxy(req, res, url) {
  let payload;
  try {
    payload = decodeProxyPayload(url.searchParams.get("p") || "");
  } catch {
    res.writeHead(400).end("bad proxy payload");
    return;
  }
  if (!payload?.url) {
    res.writeHead(400).end("url required");
    return;
  }

  const upstreamUrl = normalizeFetchUrl(payload.url);

  // Reject relative / broken upstreams early (e.g. "/video/error")
  if (!/^https?:\/\//i.test(upstreamUrl)) {
    res.writeHead(400, {
      "Content-Type": "text/plain; charset=utf-8",
      "Access-Control-Allow-Origin": "*",
    });
    res.end(`invalid upstream url: ${payload.url}`);
    return;
  }

  const headers = normalizeProxyHeaders({
    ...defaultHeadersForUrl(upstreamUrl),
    ...(payload.headers || {}),
  });
  const range = req.headers.range;
  if (range) headers.Range = range;

  let upstream;
  try {
    upstream = await safeFetch(upstreamUrl, {
      headers,
      redirect: "follow",
    });
  } catch (e) {
    const detail = e.cause?.code || e.message;
    res.writeHead(502, {
      "Content-Type": "text/plain; charset=utf-8",
      "Access-Control-Allow-Origin": "*",
    });
    res.end(`upstream fetch failed: ${detail}`);
    return;
  }

  const contentType = upstream.headers.get("content-type") || "";
  const isPlaylist =
    /mpegurl|m3u8|application\/vnd\.apple\.mpegurl/i.test(contentType) ||
    /\.m3u8(\?|$)/i.test(payload.url);

  const outHeaders = {
    "Access-Control-Allow-Origin": "*",
    "Access-Control-Expose-Headers": "Content-Length, Content-Range, Accept-Ranges, X-Upstream-Status",
    "Cache-Control": "no-store",
    "X-Upstream-Status": String(upstream.status),
  };
  for (const key of [
    "content-type",
    "content-length",
    "accept-ranges",
    "content-range",
  ]) {
    const value = upstream.headers.get(key);
    if (value) outHeaders[key] = value;
  }

  // If the browser disconnects, cancel upstream so undici doesn't sit paused
  const onClientGone = () => cancelBody(upstream.body);
  req.on("close", onClientGone);
  res.on("close", onClientGone);

  if (isPlaylist) {
    let text;
    try {
      text = await upstream.text();
    } catch (e) {
      cancelBody(upstream.body);
      if (!res.headersSent) {
        res.writeHead(502, {
          "Content-Type": "text/plain; charset=utf-8",
          "Access-Control-Allow-Origin": "*",
        });
      }
      res.end(`playlist read failed: ${e.message}`);
      return;
    }
    if (upstream.status >= 400) {
      res.writeHead(upstream.status, {
        ...outHeaders,
        "Content-Type": "text/plain; charset=utf-8",
      });
      res.end(text || `upstream playlist error ${upstream.status}`);
      return;
    }
    const rewritten = rewriteM3u8(
      text,
      upstream.url || payload.url,
      payload.headers || {},
    );
    outHeaders["Content-Type"] = "application/vnd.apple.mpegurl; charset=utf-8";
    delete outHeaders["content-length"];
    res.writeHead(200, outHeaders);
    res.end(rewritten);
    return;
  }

  if (upstream.status >= 400) {
    let text = "";
    try {
      text = await upstream.text();
    } catch {
      cancelBody(upstream.body);
    }
    res.writeHead(upstream.status, {
      ...outHeaders,
      "Content-Type": contentType || "text/plain; charset=utf-8",
    });
    res.end(text || `upstream error ${upstream.status}`);
    return;
  }

  res.writeHead(upstream.status, outHeaders);
  if (!upstream.body) {
    res.end();
    return;
  }

  let nodeStream;
  try {
    nodeStream = Readable.fromWeb(upstream.body);
  } catch (e) {
    cancelBody(upstream.body);
    res.end();
    return;
  }
  nodeStream.on("error", (err) => {
    console.error("[lab] proxy stream error:", err.message);
    cancelBody(upstream.body);
    if (!res.writableEnded) res.destroy(err);
  });
  res.on("error", () => {
    nodeStream.destroy();
    cancelBody(upstream.body);
  });
  nodeStream.pipe(res);
}

function sseWrite(res, event, data) {
  res.write(`event: ${event}\n`);
  res.write(`data: ${JSON.stringify(data)}\n\n`);
}

const server = http.createServer(async (req, res) => {
  try {
    const url = new URL(req.url, `http://${req.headers.host}`);
    const host = `http://${req.headers.host}`;

    if (req.method === "OPTIONS") {
      res.writeHead(204, {
        "Access-Control-Allow-Origin": "*",
        "Access-Control-Allow-Methods": "GET,POST,OPTIONS",
        "Access-Control-Allow-Headers": "Content-Type, Range",
        "Access-Control-Expose-Headers": "Content-Length, Content-Range, Accept-Ranges",
      });
      res.end();
      return;
    }

    if (req.method === "GET" && (url.pathname === "/" || url.pathname === "/index.html")) {
      const html = fs.readFileSync(path.join(publicDir, "index.html"), "utf8");
      res.writeHead(200, { "Content-Type": "text/html; charset=utf-8" });
      res.end(html);
      return;
    }

    if (req.method === "GET" && url.pathname.startsWith("/assets/")) {
      const rel = path.normalize(url.pathname.slice(1));
      const file = path.resolve(publicDir, rel);
      const assetsRoot = path.resolve(publicDir, "assets");
      if (!file.startsWith(assetsRoot + path.sep) || !fs.existsSync(file)) {
        res.writeHead(404).end("Not found");
        return;
      }
      const ext = path.extname(file);
      const types = {
        ".css": "text/css; charset=utf-8",
        ".js": "text/javascript; charset=utf-8",
        ".mjs": "text/javascript; charset=utf-8",
      };
      res.writeHead(200, { "Content-Type": types[ext] || "application/octet-stream" });
      res.end(fs.readFileSync(file));
      return;
    }

    if (req.method === "GET" && url.pathname === "/api/proxy") {
      await handleProxy(req, res, url);
      return;
    }

    // P-Stream userscript `makeRequest` equivalent (no Tampermonkey).
    if (req.method === "POST" && url.pathname === "/api/fetch") {
      await handleApiFetch(req, res);
      return;
    }

    if (req.method === "GET" && url.pathname === "/api/providers") {
      const includeDisabled = url.searchParams.get("all") === "1";
      const sources = scrapers.registeredSources
        .filter((s) => includeDisabled || !s.disabled)
        .map((s) => ({
          id: s.id,
          name: s.name,
          rank: s.rank,
          disabled: Boolean(s.disabled),
          mediaTypes: s.mediaTypes || [],
        }))
        .sort((a, b) => b.rank - a.rank);
      const movieCapable = scrapers.registeredSources.filter((s) => s.scrapeMovie);
      json(res, 200, {
        sources,
        totals: {
          sources: scrapers.registeredSources.length,
          embeds: scrapers.registeredEmbeds.length,
          enabledSources: scrapers.registeredSources.filter((s) => !s.disabled).length,
          enabledMovieSources: movieCapable.filter((s) => !s.disabled).length,
          allMovieSources: movieCapable.length,
        },
        tmdbSearchEnabled: Boolean(TMDB_KEY || TMDB_TOKEN),
      });
      return;
    }

    if (req.method === "GET" && url.pathname === "/api/search") {
      const q = url.searchParams.get("q") || "";
      if (!q.trim()) return json(res, 400, { error: "q required" });
      json(res, 200, await tmdbSearch(q.trim()));
      return;
    }

    if (req.method === "GET" && url.pathname === "/api/party/rooms") {
      const rooms = [];
      for (const [code, peers] of partyRooms.entries()) {
        if (!peers || peers.size === 0) continue;
        const meta = partyRoomMeta.get(code) || {};
        rooms.push({
          roomCode: code,
          contentId: meta.contentId || null,
          title: meta.title || null,
          hostName: meta.hostName || null,
          viewers: peers.size,
          updatedAt: meta.updatedAt || null,
          hasStream: Boolean(meta.stream?.playable?.url),
        });
      }
      rooms.sort((a, b) => (b.updatedAt || 0) - (a.updatedAt || 0));
      json(res, 200, { rooms });
      return;
    }

    if (req.method === "GET" && url.pathname.startsWith("/api/party/room/")) {
      const code = decodeURIComponent(url.pathname.slice("/api/party/room/".length))
        .trim()
        .toUpperCase();
      if (!code) return json(res, 400, { error: "code required" });
      const meta = partyRoomMeta.get(code);
      const live = partyRooms.has(code) && partyRooms.get(code).size > 0;
      if (!meta && !live) {
        return json(res, 404, { error: "Room not found", exists: false });
      }
      json(res, 200, {
        exists: true,
        roomCode: code,
        contentId: meta?.contentId || null,
        title: meta?.title || null,
        hostName: meta?.hostName || null,
        viewers: live ? partyRooms.get(code).size : 0,
        stream: meta?.stream || null,
      });
      return;
    }

    if (req.method === "GET" && url.pathname === "/api/popular") {
      const movieLimit = Math.max(1, Math.min(20, Number(url.searchParams.get("movies") || 5)));
      const tvLimit = Math.max(1, Math.min(20, Number(url.searchParams.get("tv") || 10)));
      if (!TMDB_KEY && !TMDB_TOKEN) {
        return json(res, 400, { error: "TMDB key not configured" });
      }
      async function fetchPopular(kind, limit, type) {
        const popularUrl = new URL(`https://api.themoviedb.org/3/${kind}/popular`);
        if (!TMDB_TOKEN) popularUrl.searchParams.set("api_key", TMDB_KEY);
        const resTmdb = await fetch(popularUrl, { headers: tmdbHeaders() });
        if (!resTmdb.ok) throw new Error(`TMDB popular ${kind} failed: ${resTmdb.status}`);
        const data = await resTmdb.json();
        return (data.results || []).slice(0, limit).map((item) => mapTmdbListItem(item, type));
      }
      const [movies, tv] = await Promise.all([
        fetchPopular("movie", movieLimit, "movie"),
        fetchPopular("tv", tvLimit, "show"),
      ]);
      json(res, 200, { movies, tv });
      return;
    }

    // Catalog rails: movies | tv | anime × popular | newest | top
    // Anime uses TMDB keyword 210024 ("anime") — more precise than Animation+ja alone.
    if (req.method === "GET" && url.pathname === "/api/discover") {
      if (!TMDB_KEY && !TMDB_TOKEN) {
        return json(res, 400, { error: "TMDB key not configured" });
      }
      const section = (url.searchParams.get("section") || "movies").toLowerCase();
      const rail = (url.searchParams.get("rail") || "popular").toLowerCase();
      const limit = Math.max(1, Math.min(24, Number(url.searchParams.get("limit") || 16)));
      const today = new Date().toISOString().slice(0, 10);
      const ANIME_KEYWORD = "210024";

      let path;
      let type = "movie";
      const params = new URLSearchParams();

      if (section === "anime") {
        type = rail === "films" ? "movie" : "show";
        path = type === "movie" ? "/discover/movie" : "/discover/tv";
        params.set("with_keywords", ANIME_KEYWORD);
        if (rail === "airing") {
          // Recently aired episodes (anime keyword + air window)
          const past = new Date();
          past.setDate(past.getDate() - 21);
          params.set("sort_by", "popularity.desc");
          params.set("air_date.gte", past.toISOString().slice(0, 10));
          params.set("air_date.lte", today);
        } else if (rail === "newest") {
          params.set("sort_by", type === "movie" ? "primary_release_date.desc" : "first_air_date.desc");
          if (type === "movie") params.set("primary_release_date.lte", today);
          else params.set("first_air_date.lte", today);
        } else if (rail === "top") {
          params.set("sort_by", "vote_average.desc");
          params.set("vote_count.gte", "80");
        } else {
          // popular (default) + films
          params.set("sort_by", "popularity.desc");
        }
      } else if (section === "tv") {
        type = "show";
        if (rail === "newest") {
          path = "/discover/tv";
          params.set("sort_by", "first_air_date.desc");
          params.set("first_air_date.lte", today);
        } else if (rail === "top") {
          path = "/discover/tv";
          params.set("sort_by", "vote_average.desc");
          params.set("vote_count.gte", "200");
        } else {
          path = "/tv/popular";
        }
      } else {
        // movies
        type = "movie";
        if (rail === "newest") {
          path = "/discover/movie";
          params.set("sort_by", "primary_release_date.desc");
          params.set("primary_release_date.lte", today);
        } else if (rail === "top") {
          path = "/discover/movie";
          params.set("sort_by", "vote_average.desc");
          params.set("vote_count.gte", "300");
        } else {
          path = "/movie/popular";
        }
      }

      const tmdbUrl = new URL(`https://api.themoviedb.org/3${path}`);
      for (const [k, v] of params.entries()) tmdbUrl.searchParams.set(k, v);
      if (!TMDB_TOKEN) tmdbUrl.searchParams.set("api_key", TMDB_KEY);
      const resTmdb = await fetch(tmdbUrl, { headers: tmdbHeaders() });
      if (!resTmdb.ok) throw new Error(`TMDB discover failed: ${resTmdb.status}`);
      const data = await resTmdb.json();
      const results = (data.results || []).slice(0, limit).map((item) => mapTmdbListItem(item, type));
      json(res, 200, { section, rail, results });
      return;
    }

    if (req.method === "GET" && url.pathname === "/api/subtitles") {
      await handleSubtitlesSearch(req, res, url);
      return;
    }

    if (req.method === "POST" && url.pathname === "/api/subtitles/download") {
      const body = await readBody(req);
      const fileId = body?.fileId;
      if (!fileId) return json(res, 400, { error: "fileId required" });
      try {
        const link = await resolveOpenSubtitlesDownload(fileId);
        if (!link) return json(res, 400, { error: "OPENSUBTITLES_API_KEY not configured" });
        json(res, 200, { url: link });
      } catch (e) {
        json(res, 502, { error: e.message || "download failed" });
      }
      return;
    }

    if (req.method === "GET" && url.pathname === "/api/season") {
      const id = (url.searchParams.get("id") || "").trim();
      const season = Math.max(0, Number(url.searchParams.get("season") || 1) || 1);
      if (!id) return json(res, 400, { error: "id required" });
      if (!TMDB_KEY && !TMDB_TOKEN) {
        return json(res, 400, { error: "TMDB key not configured" });
      }
      const seasonUrl = new URL(`https://api.themoviedb.org/3/tv/${id}/season/${season}`);
      if (!TMDB_TOKEN) seasonUrl.searchParams.set("api_key", TMDB_KEY);
      const resTmdb = await fetch(seasonUrl, { headers: tmdbHeaders() });
      if (!resTmdb.ok) throw new Error(`TMDB season failed: ${resTmdb.status}`);
      const item = await resTmdb.json();
      const episodes = Array.isArray(item.episodes)
        ? item.episodes.map((ep) => ({
            episodeNumber: Number(ep.episode_number) || 0,
            seasonNumber: Number(ep.season_number) || season,
            name: ep.name || `Episode ${ep.episode_number}`,
            overview: ep.overview || "",
            still: ep.still_path
              ? `https://image.tmdb.org/t/p/w500${ep.still_path}`
              : null,
            runtime: Number(ep.runtime) || null,
            airDate: ep.air_date || null,
          }))
        : [];
      json(res, 200, {
        tmdbId: id,
        seasonNumber: Number(item.season_number) || season,
        name: item.name || `Season ${season}`,
        overview: item.overview || "",
        poster: item.poster_path
          ? `https://image.tmdb.org/t/p/w500${item.poster_path}`
          : null,
        episodes,
      });
      return;
    }

    if (req.method === "GET" && url.pathname === "/api/aniskip") {
      const title = (url.searchParams.get("title") || "").trim();
      const tmdbId = (url.searchParams.get("tmdbId") || "").trim();
      const episode = Math.max(1, Number(url.searchParams.get("episode") || 0) || 0);
      const episodeLength = Math.max(0, Number(url.searchParams.get("episodeLength") || 0) || 0);
      const malOverride = Math.max(0, Number(url.searchParams.get("malId") || 0) || 0);
      const year = Number(url.searchParams.get("year") || 0) || null;
      if (!episode) return json(res, 400, { error: "episode required" });
      if (!malOverride && !title && !tmdbId) {
        return json(res, 400, { error: "title or malId required" });
      }

      let malId = malOverride;
      if (!malId) {
        let searchTitle = title;
        if (!searchTitle && tmdbId && (TMDB_KEY || TMDB_TOKEN)) {
          try {
            const detailUrl = new URL(`https://api.themoviedb.org/3/tv/${tmdbId}`);
            if (!TMDB_TOKEN) detailUrl.searchParams.set("api_key", TMDB_KEY);
            const detailRes = await fetch(detailUrl, { headers: tmdbHeaders() });
            if (detailRes.ok) {
              const item = await detailRes.json();
              searchTitle = item.name || item.original_name || "";
            }
          } catch {
            /* ignore */
          }
        }
        malId = await resolveMalIdFromAniList(searchTitle, year);
      }
      if (!malId) {
        return json(res, 200, { found: false, malId: null, episode, results: [] });
      }

      const skipUrl = new URL(`https://api.aniskip.com/v2/skip-times/${malId}/${episode}`);
      for (const t of ["op", "ed", "mixed-op", "mixed-ed", "recap"]) {
        skipUrl.searchParams.append("types", t);
      }
      if (episodeLength > 0) {
        skipUrl.searchParams.set("episodeLength", episodeLength.toFixed(3));
      }

      const skipRes = await safeFetch(skipUrl.toString(), {
        headers: { Accept: "application/json", "User-Agent": BROWSER_UA },
      });
      if (!skipRes.ok) {
        cancelBody(skipRes.body);
        return json(res, 200, {
          found: false,
          malId,
          episode,
          results: [],
          error: `aniskip ${skipRes.status}`,
        });
      }
      const data = await skipRes.json();
      const results = Array.isArray(data?.results)
        ? data.results
            .map((r) => ({
              skipId: String(r.skipId || `${r.skipType}-${r.interval?.startTime}`),
              skipType: String(r.skipType || ""),
              startTime: Number(r.interval?.startTime) || 0,
              endTime: Number(r.interval?.endTime) || 0,
              episodeLength: Number(r.episodeLength) || episodeLength || 0,
            }))
            .filter((r) => r.endTime > r.startTime && r.skipType)
        : [];
      json(res, 200, {
        found: Boolean(data?.found && results.length),
        malId,
        episode,
        results,
      });
      return;
    }

    if (req.method === "GET" && url.pathname === "/api/details") {
      const type = url.searchParams.get("type") === "show" ? "show" : "movie";
      const id = (url.searchParams.get("id") || "").trim();
      if (!id) return json(res, 400, { error: "id required" });
      if (!TMDB_KEY && !TMDB_TOKEN) {
        return json(res, 400, { error: "TMDB key not configured" });
      }
      const kind = type === "show" ? "tv" : "movie";
      const detailUrl = new URL(`https://api.themoviedb.org/3/${kind}/${id}`);
      detailUrl.searchParams.set("append_to_response", "keywords");
      if (!TMDB_TOKEN) detailUrl.searchParams.set("api_key", TMDB_KEY);
      const resTmdb = await fetch(detailUrl, { headers: tmdbHeaders() });
      if (!resTmdb.ok) throw new Error(`TMDB details failed: ${resTmdb.status}`);
      const item = await resTmdb.json();
      const seasons =
        type === "show" && Array.isArray(item.seasons)
          ? item.seasons
              .filter((s) => s && Number(s.season_number) >= 0)
              .map((s) => ({
                seasonNumber: Number(s.season_number) || 0,
                episodeCount: Number(s.episode_count) || 0,
                name: s.name || `Season ${s.season_number}`,
              }))
          : undefined;
      json(res, 200, {
        tmdbId: String(item.id),
        type,
        title: item.title || item.name,
        releaseYear:
          Number((item.release_date || item.first_air_date || "").slice(0, 4)) || null,
        overview: item.overview || "",
        originalLanguage: item.original_language || null,
        isAnime: detectIsAnime(item),
        poster: item.poster_path
          ? `https://image.tmdb.org/t/p/w500${item.poster_path}`
          : null,
        backdrop: item.backdrop_path
          ? `https://image.tmdb.org/t/p/w1280${item.backdrop_path}`
          : null,
        ...(seasons ? { seasons, numberOfSeasons: Number(item.number_of_seasons) || seasons.length } : {}),
      });
      return;
    }

    if (req.method === "POST" && url.pathname === "/api/scan") {
      const body = await readBody(req);
      const media = await enrichMedia(buildMedia(body));
      const includeDisabled = body.includeDisabled === true;
      const concurrency = Math.max(1, Math.min(20, Number(body.concurrency) || 10));
      const fetcher = createHttpFetcher();
      const candidates = candidateSources(media, includeDisabled);
      const started = Date.now();

      const results = await mapPool(candidates, concurrency, (provider) =>
        probeProvider(provider, media, fetcher, FEATURES, host, false),
      );

      const found = results.filter((r) => r.status === "found" || r.playables.length);
      const missed = results.filter((r) => !found.includes(r));

      json(res, 200, {
        ok: found.length > 0,
        ms: Date.now() - started,
        media,
        concurrency,
        includeDisabled,
        scanned: results.length,
        candidateTotal: candidates.length,
        foundCount: found.length,
        missedCount: missed.length,
        found: found.sort((a, b) => b.rank - a.rank),
        missed: missed.sort((a, b) => b.rank - a.rank),
      });
      return;
    }

    if (req.method === "POST" && url.pathname === "/api/race") {
      const body = await readBody(req);
      const media = await enrichMedia(buildMedia(body));
      const includeDisabled = body.includeDisabled === true;
      const concurrency = Math.max(1, Math.min(24, Number(body.concurrency) || 12));
      const fetcher = createHttpFetcher();
      const candidates = candidateSources(media, includeDisabled);

      res.writeHead(200, {
        "Content-Type": "text/event-stream; charset=utf-8",
        "Cache-Control": "no-cache, no-transform",
        Connection: "keep-alive",
        "Access-Control-Allow-Origin": "*",
      });

      let closed = false;
      req.on("close", () => {
        closed = true;
      });

      const started = Date.now();
      let tried = 0;
      let playableCount = 0;

      sseWrite(res, "start", {
        total: candidates.length,
        includeDisabled,
        concurrency,
        media,
      });

      await mapPool(candidates, concurrency, async (provider) => {
        if (closed) return null;
        const result = await probeProvider(
          provider,
          media,
          fetcher,
          FEATURES,
          host,
          true,
        );
        if (closed) return result;
        tried += 1;
        sseWrite(res, "progress", {
          tried,
          total: candidates.length,
          id: result.id,
          name: result.name,
          status: result.status,
          ms: result.ms,
          message: result.message,
        });
        for (const item of result.playables) {
          playableCount += 1;
          sseWrite(res, "stream", {
            sourceId: item.sourceId,
            sourceName: item.sourceName,
            embedId: item.embedId,
            embedName: item.embedName,
            playable: item.playable,
            index: playableCount,
          });
        }
        return result;
      });

      if (!closed) {
        sseWrite(res, "done", {
          ms: Date.now() - started,
          tried,
          total: candidates.length,
          playableCount,
        });
        res.end();
      }
      return;
    }

    res.writeHead(404).end("Not found");
  } catch (e) {
    if (!res.headersSent) {
      json(res, 500, { error: e.message || String(e) });
    } else {
      try {
        sseWrite(res, "error", { error: e.message || String(e) });
        res.end();
      } catch {
        /* ignore */
      }
    }
  }
});

function touchPartyMeta(msg) {
  if (!msg?.roomCode) return;
  const code = String(msg.roomCode).trim().toUpperCase();
  if (msg.type === "join" && msg.isHost && msg.contentId) {
    const prev = partyRoomMeta.get(code) || {};
    partyRoomMeta.set(code, {
      contentId: String(msg.contentId),
      title: msg.title ? String(msg.title) : prev.title || null,
      hostName: msg.displayName ? String(msg.displayName) : "Host",
      stream: prev.stream || null,
      updatedAt: Date.now(),
    });
  }
  if (msg.type === "status" && msg.isHost && msg.contentId) {
    const prev = partyRoomMeta.get(code) || {};
    partyRoomMeta.set(code, {
      contentId: String(msg.contentId),
      title: msg.title ? String(msg.title) : prev.title || null,
      hostName: msg.displayName ? String(msg.displayName) : prev.hostName || "Host",
      stream: msg.provider?.playable?.url ? msg.provider : prev.stream || null,
      updatedAt: Date.now(),
    });
  }
}

const wss = new WebSocketServer({ server, path: "/api/party" });
wss.on("connection", (socket) => {
  let roomCode = null;

  socket.on("message", (raw) => {
    let msg;
    try {
      msg = JSON.parse(String(raw));
    } catch {
      return;
    }
    if (!msg || typeof msg !== "object" || !msg.type) return;

    if (msg.type === "join" && msg.roomCode) {
      const next = String(msg.roomCode).trim().toUpperCase();
      if (roomCode && partyRooms.has(roomCode)) {
        partyRooms.get(roomCode).delete(socket);
      }
      roomCode = next;
      if (!partyRooms.has(roomCode)) partyRooms.set(roomCode, new Set());
      partyRooms.get(roomCode).add(socket);
    }

    touchPartyMeta(msg);

    if (!roomCode) return;
    const peers = partyRooms.get(roomCode);
    if (!peers) return;
    const payload = JSON.stringify(msg);
    for (const peer of peers) {
      if (peer !== socket && peer.readyState === 1) {
        peer.send(payload);
      }
    }
  });

  socket.on("close", () => {
    if (!roomCode) return;
    const peers = partyRooms.get(roomCode);
    if (!peers) return;
    peers.delete(socket);
    if (peers.size === 0) {
      partyRooms.delete(roomCode);
      partyRoomMeta.delete(roomCode);
    }
  });
});

const HOST = process.env.HOST || "0.0.0.0";
server.on("error", (err) => {
  console.error(`[lab] server error: ${err.code || err.message}`);
  process.exit(1);
});
server.listen(PORT, HOST, () => {
  console.log(`Scraper lab → http://${HOST}:${PORT}`);
  if (!TMDB_KEY) {
    console.log("(optional) set TMDB_API_KEY for title search");
  }
});
