/**
 * Anisurge extension catalog → CINEMAYA source providers.
 * Declarative .asx pipelines from https://github.com/Anisurge/extensions
 */
"use strict";

const ANISURGE_UA =
  "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36";

const SCRAPER_API = "https://fetch.n92dev.us.kg/api";
const ANIVEXA_API = "https://anivexa-api.vercel.app";
const MEGAPLAY = "https://megaplay.buzz";

function episodeNumber(media) {
  if (media?.type === "movie") return 1;
  return Math.max(1, Number(media?.episode?.number || 1));
}

function guessStreamType(url, hint) {
  const value = `${url || ""} ${hint || ""}`.toLowerCase();
  if (/\.m3u8(\?|$)/i.test(value) || value.includes("mpegurl") || value.includes("hls")) {
    return "hls";
  }
  return "file";
}

function mapCaptions(list, urlKey = "file", labelKey = "label") {
  if (!Array.isArray(list)) return [];
  return list
    .map((item, index) => {
      const url = item?.[urlKey] || item?.url || item?.file;
      if (!url || !/^https?:\/\//i.test(String(url))) return null;
      const label = String(item?.[labelKey] || item?.label || item?.lang || `Track ${index + 1}`);
      return {
        id: `cap-${index}-${label}`,
        type: /\.srt(\?|$)/i.test(url) ? "srt" : "vtt",
        url: String(url),
        language: label,
        hasCorsRestrictions: false,
      };
    })
    .filter(Boolean);
}

function toStream({ url, headers, captions, displayName, id, quality }) {
  if (!url || !/^https?:\/\//i.test(String(url))) return null;
  const type = guessStreamType(url, quality);
  const base = {
    id: id || displayName || "primary",
    displayName: displayName || null,
    flags: ["cors-allowed"],
    captions: captions || [],
    headers: headers || {},
  };
  if (type === "hls") {
    return { ...base, type: "hls", playlist: String(url) };
  }
  return {
    ...base,
    type: "file",
    qualities: {
      [quality || "unknown"]: { type: "mp4", url: String(url) },
    },
  };
}

function pickPath(obj, path) {
  if (!obj || !path) return undefined;
  return String(path)
    .split(".")
    .reduce((acc, key) => (acc == null ? undefined : acc[key]), obj);
}

function streamFromScrapeBranch(branch, lang) {
  if (!branch?.streams?.length) return null;
  const first = branch.streams[0];
  const headers = {
    "User-Agent": ANISURGE_UA,
    ...(first.headers || {}),
  };
  if (first.headers?.Referer) headers.Referer = first.headers.Referer;
  if (first.headers?.Origin) headers.Origin = first.headers.Origin;
  return toStream({
    url: first.url,
    quality: first.quality,
    headers,
    captions: mapCaptions(first.subtitles, "url", "label"),
    displayName: lang === "dub" ? "Dub" : "Sub",
    id: lang === "dub" ? "dub" : "sub",
  });
}

async function scrapeAnisurgeBatch(context, sourceId) {
  const anilistId = await context.lookupAnilistId(context, context.media);
  const episode = episodeNumber(context.media);
  const url = `${SCRAPER_API}?action=batch_scrape&anilistId=${encodeURIComponent(
    anilistId,
  )}&episode=${encodeURIComponent(episode)}&source=${encodeURIComponent(sourceId)}`;
  const raw = await context.proxiedFetcher(url, {
    headers: {
      Accept: "application/json, text/plain, */*",
      "User-Agent": ANISURGE_UA,
    },
  });
  const scrape = typeof raw === "string" ? JSON.parse(raw) : raw;
  const streams = [];
  for (const lang of ["sub", "dub"]) {
    const hit = streamFromScrapeBranch(scrape?.[lang], lang);
    if (hit) streams.push(hit);
  }
  if (!streams.length) throw new context.ScraperError(`No ${sourceId} streams`);
  return { stream: streams, embeds: [] };
}

async function scrapeAnivexaAnikoto(context) {
  const anilistId = await context.lookupAnilistId(context, context.media);
  const episode = episodeNumber(context.media);
  const streams = [];
  for (const lang of ["sub", "dub"]) {
    try {
      const raw = await context.proxiedFetcher(
        `${ANIVEXA_API}/watch/anikoto/${anilistId}/${lang}/anikoto-${episode}`,
        {
          headers: {
            Accept: "application/json, text/plain, */*",
            "User-Agent": ANISURGE_UA,
            Referer: `${ANIVEXA_API}/`,
          },
        },
      );
      const watch = typeof raw === "string" ? JSON.parse(raw) : raw;
      const branch = lang === "dub" ? watch?.sdub : watch?.ssub;
      const first = branch?.streams?.[0];
      if (!first?.url) continue;
      streams.push(
        toStream({
          url: first.url,
          headers: {
            "User-Agent": ANISURGE_UA,
            Referer: first.referer || `${ANIVEXA_API}/`,
          },
          captions: mapCaptions(branch?.subtitles, "file", "label"),
          displayName: lang === "dub" ? "Dub" : "Sub",
          id: lang,
          quality: "Auto",
        }),
      );
    } catch {
      /* try other lang */
    }
  }
  if (!streams.length) throw new context.ScraperError("No Anivexa AniKoto streams");
  return { stream: streams.filter(Boolean), embeds: [] };
}

async function scrapeAnivexaSimple(context, providerKey) {
  const anilistId = await context.lookupAnilistId(context, context.media);
  const episode = episodeNumber(context.media);
  const streams = [];
  for (const lang of ["sub", "dub"]) {
    try {
      const raw = await context.proxiedFetcher(
        `${ANIVEXA_API}/watch/${providerKey}/${anilistId}/${lang}/${providerKey}-${episode}`,
        {
          headers: {
            Accept: "application/json, text/plain, */*",
            "User-Agent": ANISURGE_UA,
            Referer: `${ANIVEXA_API}/`,
          },
        },
      );
      const watch = typeof raw === "string" ? JSON.parse(raw) : raw;
      const first = watch?.streams?.[0];
      if (!first?.url) continue;
      streams.push(
        toStream({
          url: first.url,
          quality: first.quality || "Auto",
          headers: {
            "User-Agent": ANISURGE_UA,
            Referer: first.referer || `${ANIVEXA_API}/`,
          },
          displayName: lang === "dub" ? "Dub" : "Sub",
          id: lang,
        }),
      );
    } catch {
      /* try other lang */
    }
  }
  if (!streams.length) throw new context.ScraperError(`No Anivexa ${providerKey} streams`);
  return { stream: streams.filter(Boolean), embeds: [] };
}

async function lookupMalId(context, anilistId) {
  try {
    const response = await context.proxiedFetcher("", {
      baseUrl: "https://graphql.anilist.co",
      method: "POST",
      headers: { "Content-Type": "application/json", Accept: "application/json" },
      body: JSON.stringify({
        query: "query ($id: Int) { Media(id: $id, type: ANIME) { idMal } }",
        variables: { id: Number(anilistId) },
      }),
    });
    return Number(response?.data?.Media?.idMal || 0) || 0;
  } catch {
    return 0;
  }
}

async function scrapeAnokoto(context) {
  const anilistId = await context.lookupAnilistId(context, context.media);
  const malId = await lookupMalId(context, anilistId);
  const episode = episodeNumber(context.media);
  const streams = [];

  for (const lang of ["sub", "dub"]) {
    try {
      let embedHtml = "";
      try {
        embedHtml = await context.proxiedFetcher(
          `${MEGAPLAY}/stream/ani/${anilistId}/${episode}/${lang}`,
          {
            headers: {
              Accept: "text/html, */*",
              "User-Agent": ANISURGE_UA,
              Referer: `${MEGAPLAY}/`,
            },
          },
        );
      } catch {
        if (!malId) throw new Error("no ani embed");
        embedHtml = await context.proxiedFetcher(
          `${MEGAPLAY}/stream/mal/${malId}/${episode}/${lang}`,
          {
            headers: {
              Accept: "text/html, */*",
              "User-Agent": ANISURGE_UA,
              Referer: `${MEGAPLAY}/`,
            },
          },
        );
      }
      const html = typeof embedHtml === "string" ? embedHtml : String(embedHtml || "");
      const dataId =
        html.match(/id="megaplay-player"[^>]*data-id="(\d+)"/)?.[1] ||
        html.match(/data-id="(\d+)"/)?.[1];
      if (!dataId) continue;
      const sourcesBody = await context.proxiedFetcher(
        `${MEGAPLAY}/stream/getSources?id=${encodeURIComponent(dataId)}`,
        {
          headers: {
            Accept: "application/json, text/plain, */*",
            "X-Requested-With": "XMLHttpRequest",
            "User-Agent": ANISURGE_UA,
            Referer: `${MEGAPLAY}/`,
          },
        },
      );
      const sources = typeof sourcesBody === "string" ? JSON.parse(sourcesBody) : sourcesBody;
      const file = pickPath(sources, "sources.file");
      if (!file) continue;
      streams.push(
        toStream({
          url: file,
          quality: "Auto",
          headers: {
            Referer: `${MEGAPLAY}/`,
            "User-Agent": ANISURGE_UA,
          },
          captions: mapCaptions(sources?.tracks, "file", "label"),
          displayName: lang === "dub" ? "Dub" : "Sub",
          id: lang,
        }),
      );
    } catch {
      /* try other lang */
    }
  }

  if (!streams.length) throw new context.ScraperError("No Anokoto streams");
  return { stream: streams.filter(Boolean), embeds: [] };
}

function registerAnisurgeProviders({ createSourceProvider, ScraperError, lookupAnilistId }) {
  const withCtx = (fn) => async (context) =>
    fn({
      ...context,
      ScraperError,
      lookupAnilistId,
    });

  const batch = [
    ["scraper-2dhive", "2D Hive", "2dhive", 894],
    ["scraper-animegg", "AnimeGG", "animegg", 893],
    ["scraper-animeheaven", "AnimeHeaven", "animeheaven", 892],
    ["scraper-anineko", "AniNeko", "anineko", 891],
    ["scraper-anitaku", "Anitaku", "anitaku", 890],
    ["scraper-mkissa", "MKissa", "mkissa", 889],
    ["scraper-suzu", "Suzu", "suzu", 888],
  ];

  for (const [id, name, source, rank] of batch) {
    createSourceProvider({
      id,
      name,
      rank,
      disabled: false,
      flags: ["cors-allowed"],
      scrapeShow: withCtx((ctx) => scrapeAnisurgeBatch(ctx, source)),
      scrapeMovie: withCtx((ctx) => scrapeAnisurgeBatch(ctx, source)),
    });
  }

  createSourceProvider({
    id: "anivexa-anikoto",
    name: "Anivexa AniKoto",
    rank: 897,
    disabled: false,
    flags: ["cors-allowed"],
    scrapeShow: withCtx(scrapeAnivexaAnikoto),
    scrapeMovie: withCtx(scrapeAnivexaAnikoto),
  });

  createSourceProvider({
    id: "anivexa-animegg",
    name: "Anivexa AnimeGG",
    rank: 896,
    disabled: false,
    flags: ["cors-allowed"],
    scrapeShow: withCtx((ctx) => scrapeAnivexaSimple(ctx, "animegg")),
    scrapeMovie: withCtx((ctx) => scrapeAnivexaSimple(ctx, "animegg")),
  });

  createSourceProvider({
    id: "anivexa-anineko",
    name: "Anivexa AniNeko",
    rank: 895,
    disabled: false,
    flags: ["cors-allowed"],
    scrapeShow: withCtx((ctx) => scrapeAnivexaSimple(ctx, "anineko")),
    scrapeMovie: withCtx((ctx) => scrapeAnivexaSimple(ctx, "anineko")),
  });

  createSourceProvider({
    id: "anokoto",
    name: "Anokoto",
    rank: 898,
    disabled: false,
    flags: ["cors-allowed"],
    scrapeShow: withCtx(scrapeAnokoto),
    scrapeMovie: withCtx(scrapeAnokoto),
  });
}

module.exports = { registerAnisurgeProviders };
