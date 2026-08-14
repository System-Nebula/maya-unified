/**
 * Focused scraper/provider extraction from vendor-ONLY(1).js
 *
 * Includes the scraper runtime, provider lookup/selection logic, all registered
 * source and embed providers, and their directly adjacent helper functions.
 * Vendor UI/runtime libraries were intentionally excluded.
 *
 * Registered provider count: 135
 */
"use strict";

const CryptoJS = require("crypto-js");
const cheerio = require("cheerio");
const uA = require("tweetnacl");
const gh = require("iso-639-1");

class ScraperError extends Error {
    constructor(message) {
        super(message ?? "not found");
        this.name = "ScraperError";
    }
}

const streamProxyEndpoint = "https://proxy.nsbx.ru/proxy";
let proxyBaseUrl = "https://proxy.aether.mom";

function loadHtml(html) {
    return cheerio.load(html ?? "");
}

function normalizeFetcher(fetchImpl) {
    if (!fetchImpl) {
        throw new Error("fetcher is required");
    }
    if (typeof fetchImpl === "function" && fetchImpl.full) {
        return fetchImpl;
    }
    const full = async (url, options = {}) => {
        const result = await fetchImpl(url, options);
        if (result && typeof result === "object" && "body" in result) {
            return result;
        }
        return { body: result, statusCode: 200, headers: {}, finalUrl: url };
    };
    const fetcher = async (url, options) => (await full(url, options)).body;
    fetcher.full = full;
    return fetcher;
}

function supportsRequiredFlags(featureSet, flags) {
    if (!featureSet) return true;
    const present = flags ?? [];
    const requires = featureSet.requires ?? [];
    const disallowed = featureSet.disallowed ?? [];
    return requires.every((flag) => present.includes(flag)) &&
        !disallowed.some((flag) => present.includes(flag));
}

function getProviderMetadata(registry, providerId) {
    const source = registry.sources.find((entry) => entry.id === providerId);
    if (source) {
        return {
            type: "source",
            id: source.id,
            rank: source.rank,
            name: source.name,
            mediaTypes: source.mediaTypes,
        };
    }
    const embed = registry.embeds.find((entry) => entry.id === providerId);
    return embed
        ? { type: "embed", id: embed.id, rank: embed.rank, name: embed.name }
        : null;
}

function listSourceMetadata(registry) {
    return [...registry.sources]
        .sort((a, b) => b.rank - a.rank)
        .map((source) => ({
            type: "source",
            id: source.id,
            rank: source.rank,
            name: source.name,
            mediaTypes: source.mediaTypes,
            disabled: source.disabled,
        }));
}

function listEmbedMetadata(registry) {
    return [...registry.embeds]
        .sort((a, b) => b.rank - a.rank)
        .map((embed) => ({
            type: "embed",
            id: embed.id,
            rank: embed.rank,
            name: embed.name,
            disabled: embed.disabled,
        }));
}

const registeredSources = [];
const registeredEmbeds = [];

/** nanoid-style custom alphabet factory (was `cA` in the vendor chunk) */
function customAlphabet(alphabet, defaultSize = 21) {
    return (size = defaultSize) => {
        let output = "";
        const bytes = require("node:crypto").randomBytes(size);
        for (let i = 0; i < size; i++) {
            output += alphabet[bytes[i] % alphabet.length];
        }
        return output;
    };
}
const cA = customAlphabet;

function setProxyBaseUrl(url) {
    proxyBaseUrl = url;
}
function streamRequiresProxy(stream) {
    const hasCustomHeaders = Boolean(stream.headers && Object.keys(stream.headers).length > 0);
    return !stream.flags.includes("cors-allowed") || hasCustomHeaders;
}
function proxyStreamUrls(stream) {
    const headers = stream.headers && Object.keys(stream.headers).length > 0
        ? stream.headers
        : undefined;
    const options = stream.type === "hls"
        ? { depth: stream.proxyDepth ?? 0 }
        : {};
    const proxyPayload = { headers, options };
    if (stream.type === "hls") {
        proxyPayload.type = "hls";
        proxyPayload.url = stream.playlist;
        stream.playlist = `${streamProxyEndpoint}?${new URLSearchParams({
            payload: Buffer.from(JSON.stringify(proxyPayload)).toString("base64url")
        })}`;
    }
    if (stream.type === "file") {
        proxyPayload.type = "mp4";
        for (const quality of Object.values(stream.qualities)) {
            proxyPayload.url = quality.url;
            quality.url = `${streamProxyEndpoint}?${new URLSearchParams({
                payload: Buffer.from(JSON.stringify(proxyPayload)).toString("base64url")
            })}`;
        }
    }
    stream.headers = {};
    stream.flags = ["cors-allowed"];
    return stream;
}
function buildProxiedHlsUrl(url, featureSet, headers = {}) {
    if (featureSet && !featureSet.requires.includes("cors-allowed")) {
        return url;
    }
    const encodedUrl = encodeURIComponent(url);
    const encodedHeaders = encodeURIComponent(JSON.stringify(headers));
    return `${proxyBaseUrl}/m3u8-proxy?url=${encodedUrl}` +
        (headers ? `&headers=${encodedHeaders}` : "");
}
function rewriteProxyBaseUrl(url) {
    if (!url.includes("/m3u8-proxy?url=")) {
        return url;
    }
    return url.replace(/https:\/\/[^/]+\/m3u8-proxy/, `${proxyBaseUrl}/m3u8-proxy`);
}
function createSourceProvider(providerDefinition) {
    const mediaTypes = [];
    if (providerDefinition.scrapeMovie) {
        mediaTypes.push("movie");
    }
    if (providerDefinition.scrapeShow) {
        mediaTypes.push("show");
    }
    const provider = {
        ...providerDefinition,
        type: "source",
        disabled: providerDefinition.disabled ?? false,
        externalSource: providerDefinition.externalSource ?? false,
        mediaTypes
    };
    registeredSources.push(provider);
    return provider;
}
function createEmbedProvider(providerDefinition) {
    const provider = {
        ...providerDefinition,
        type: "embed",
        disabled: providerDefinition.disabled ?? false,
        mediaTypes: undefined
    };
    registeredEmbeds.push(provider);
    return provider;
}
async function scrapeBombtheirish(context) {
    const response = await context.proxiedFetcher("https://bombthe.irish/embed/" + (context.media.type === "movie" ? "movie/" + context.media.tmdbId : "tv/" + context.media.tmdbId + "/" + context.media.season.number + "/" + context.media.episode.number));
    const document = loadHtml(response);
    const results = [];
    document("#dropdownMenu a").each((index, element) => {
        const parsedUrl = new URL(document(element).data("url")).searchParams.get("url");
        if (parsedUrl) {
            results.push({ embedId: document(element).text().toLowerCase(), url: atob(parsedUrl) });
        }
    });
    return {
        embeds: results
    };
}
const bombtheirishProviderConfig = {
    id: "bombtheirish",
    name: "bombthe.irish",
    rank: 100,
    disabled: true,
    flags: ["cors-allowed"],
    scrapeMovie: scrapeBombtheirish,
    scrapeShow: scrapeBombtheirish
};
const bombtheirishProvider = createSourceProvider(bombtheirishProviderConfig);
const aetherServerSlots = {
    length: 30
};
const aetherServerEmbedProviders = Array.from(aetherServerSlots).map((item, index) => {
    const r = index + 1;
    return createEmbedProvider({ id: "aether-server-" + r, name: "Server " + r, rank: 550 - index, scrape: async function scrapeAetherServerEmbedProviders(context) {
            const stream = {
                id: "primary",
                type: "hls",
                playlist: context.url,
                flags: ["cors-allowed"],
                captions: []
            };
            return {
                stream: [stream]
            };
        } });
});
const femexpJett4kQuality = {
    key: "4k",
    label: "4K",
    rank: 69
};
const femexpJett1080Quality = {
    key: "1080",
    label: "1080",
    rank: 68
};
const femexpJett720Quality = {
    key: "720",
    label: "720",
    rank: 67
};
const femexpJett480Quality = {
    key: "480",
    label: "480",
    rank: 66
};
const femexpJett360Quality = {
    key: "360",
    label: "360",
    rank: 65
};
const femexpJettQualityOptions = [femexpJett4kQuality, femexpJett1080Quality, femexpJett720Quality, femexpJett480Quality, femexpJett360Quality];
function mapFemexpJettQuality(input) {
    const value = (input ?? "").toLowerCase();
    return value ? value.includes("4k") || value.includes("2160") ? "femexp-jett-4k" : value.includes("1080") ? "femexp-jett-1080" : value.includes("720") ? "femexp-jett-720" : value.includes("480") ? "femexp-jett-480" : value.includes("360") ? "femexp-jett-360" : null : null;
}
function createFemexpJettProvider(input) {
    const result = {
        id: "femexp-jett-" + input.key,
        name: "Jett " + input.label,
        rank: input.rank,
        scrape: async function scrapeFemexpJettProvider(item) {
            const stream = {
                id: "primary",
                type: "hls",
                playlist: item.url,
                flags: ["cors-allowed"],
                captions: []
            };
            return {
                stream: [stream]
            };
        }
    };
    return createEmbedProvider(result);
}
const femexpJettEmbedProviders = femexpJettQualityOptions.map(createFemexpJettProvider);
const videasyPlayerBaseUrl = "https://player.videasy.to";
const videasyProxyServerUrls = ["https://r1.aether.cx", "https://r2.aether.cx", "https://r3.aether.cx", "https://r4.aether.cx", "https://r5.aether.cx"];
const videasyProxyHeadersObject = {
    Origin: videasyPlayerBaseUrl,
    Referer: videasyPlayerBaseUrl + "/"
};
const videasyProxyHeaders = videasyProxyHeadersObject;
const videasy1080Quality = {
    key: "1080",
    label: "1080",
    rank: 74
};
const videasy720Quality = {
    key: "720",
    label: "720",
    rank: 73
};
const videasy480Quality = {
    key: "480",
    label: "480",
    rank: 72
};
const videasy360Quality = {
    key: "360",
    label: "360",
    rank: 71
};
const videasyQualityOptions = [videasy1080Quality, videasy720Quality, videasy480Quality, videasy360Quality];
function selectVideasyProxyServer() {
    return videasyProxyServerUrls[Math.floor(Math.random() * videasyProxyServerUrls.length)];
}
function buildVideasyProxyUrl(input) {
    const parsedUrl = new URL("/m3u8-proxy", selectVideasyProxyServer());
    parsedUrl.searchParams.set("url", input);
    parsedUrl.searchParams.set("headers", JSON.stringify(videasyProxyHeaders));
    return parsedUrl.toString();
}
function mapVideasyQuality(input) {
    const value = (input ?? "").toLowerCase();
    return value ? value.includes("1080") ? "videasy-cdn-1080" : value.includes("720") ? "videasy-cdn-720" : value.includes("480") ? "videasy-cdn-480" : value.includes("360") ? "videasy-cdn-360" : null : null;
}
function createVideasyCdnProvider(input) {
    return createEmbedProvider({ id: "videasy-cdn-" + input.key, name: "CDN " + input.label, rank: input.rank, scrape: async function scrapeVideasyCdnProvider(context) {
            return { stream: [{ id: "primary", type: "hls", playlist: buildVideasyProxyUrl(context.url), flags: ["cors-allowed"], captions: [] }] };
        } });
}
const videasyCdnEmbedProviders = videasyQualityOptions.map(createVideasyCdnProvider);
const warezcdnEmbedBaseUrl = "https://embed.warezcdn.link";
const warezcdnPlayerBaseUrl = "https://warezcdn.link/player";
const warezcdnWorkerProxyBaseUrl = "https://workerproxy.warezcdn.workers.dev";
function decodeWarezcdnFileId(input) {
    let value = atob(input);
    value = value.trim();
    value = value.split("").reverse().join("");
    let value3 = value.slice(-5);
    value3 = value3.split("").reverse().join("");
    value = value.slice(0, -5);
    return "" + value + value3;
}
async function lookupWarezcdnFileId(context) {
    const response = await context.proxiedFetcher("/player.php", { baseUrl: warezcdnPlayerBaseUrl, headers: { Referer: warezcdnPlayerBaseUrl + "/getEmbed.php?" + new URLSearchParams({ id: context.url, sv: "warezcdn" }) }, query: { id: context.url } });
    const match = response.match(/let allowanceKey = "(.*?)";/)?.[1];
    if (!match) {
        throw new ScraperError("Failed to get allowanceKey");
    }
    const queryParams = await context.proxiedFetcher("/functions.php", { baseUrl: warezcdnPlayerBaseUrl, method: "POST", body: new URLSearchParams({ getVideo: context.url, key: match }) });
    const data = JSON.parse(queryParams);
    if (!data.id) {
        throw new ScraperError("can't get stream id");
    }
    const value = decodeWarezcdnFileId(data.id);
    if (!value) {
        throw new ScraperError("can't get file id");
    }
    return value;
}
const warezcdnCloudServerNumbers = [50, 51, 52, 53, 54, 55, 56, 57, 58, 59, 60, 61, 62, 63, 64];
async function findWorkingWarezcdnCloudUrl(context, argument2) {
    for (const item of warezcdnCloudServerNumbers) {
        const requestUrl = "https://cloclo" + item + ".cloud.mail.ru/weblink/view/" + argument2;
        const requestOptions = {};
        if (requestOptions.method = "GET", requestOptions.headers = {}, requestOptions.headers.Range = "bytes=0-1", (await context.proxiedFetcher.full(requestUrl, requestOptions)).statusCode === 206) {
            return requestUrl;
        }
    }
    return null;
}
async function scrapeWarezcdnembedmp4(context) {
    const value = await lookupWarezcdnFileId(context);
    if (!value) {
        throw new ScraperError("can't get file id");
    }
    const url = await findWorkingWarezcdnCloudUrl(context, value);
    if (!url) {
        throw new ScraperError("can't get stream id");
    }
    const result = {
        url: url
    };
    return { stream: [{ id: "primary", captions: [], qualities: { unknown: { type: "mp4", url: warezcdnWorkerProxyBaseUrl + "/?" + new URLSearchParams(result) } }, type: "file", flags: ["cors-allowed"] }] };
}
async function scrapeYakamozDublaj(context) {
    const response = await fetch(context.url);
    if (!response.ok) {
        throw new Error("Failed to fetch from Yakamoz API");
    }
    const data = await response.json();
    if (!data.streamUrl) {
        throw new Error("No stream found");
    }
    const stream = {
        id: "primary",
        type: "hls",
        playlist: data.streamUrl,
        flags: ["cors-allowed"],
        captions: []
    };
    return {
        stream: [stream]
    };
}
async function scrapeYakamozAltyazi(context) {
    const response = await fetch(context.url);
    if (!response.ok) {
        throw new Error("Failed to fetch from Yakamoz API");
    }
    const data = await response.json();
    if (!data.streamUrl) {
        throw new Error("No stream found");
    }
    const stream = {
        id: "primary",
        type: "hls",
        playlist: data.streamUrl,
        flags: ["cors-allowed"],
        captions: []
    };
    return {
        stream: [stream]
    };
}
const warezcdnembedmp4EmbedProvider = createEmbedProvider({ id: "warezcdnembedmp4", name: "WarezCDN MP4", rank: 82, disabled: true, scrape: scrapeWarezcdnembedmp4 });
const yakamozDublajEmbedProvider = createEmbedProvider({ id: "yakamoz-dublaj", name: "Dublaj", rank: 207, scrape: scrapeYakamozDublaj });
const yakamozAltyaziEmbedProvider = createEmbedProvider({ id: "yakamoz-altyazi", name: "Altyazi", rank: 206, scrape: scrapeYakamozAltyazi });
const aetherBaseUrl = "https://play.aether.bar";
const aetherValue = "05bb7bb919b9e5185a35a61a1b72d3941d14df215619792546e3f58dc476dca4";
function aetherCreateToken(input) {
    const token = CryptoJS.enc.Hex.parse(aetherValue);
    const token5 = CryptoJS.lib.WordArray.random(16);
    const value = JSON.stringify(input);
    const token6 = CryptoJS.AES.encrypt(value, token, { iv: token5, mode: CryptoJS.mode.CTR, padding: CryptoJS.pad.NoPadding });
    const token7 = token6.ciphertext.toString(CryptoJS.enc.Hex);
    const signature = CryptoJS.HmacSHA256(token5.toString(CryptoJS.enc.Hex) + token7, token).toString(CryptoJS.enc.Hex).substring(0, 32);
    return token5.toString(CryptoJS.enc.Hex) + ":" + signature + ":" + token7;
}
async function scrapeAetherMovie(context) {
    const timestamp3 = { tmdbId: context.media.tmdbId, type: "movie", timestamp: Date.now() };
    const value = aetherCreateToken(timestamp3);
    const requestUrl = aetherBaseUrl + "/movie/" + context.media.tmdbId + "/master.m3u8?token=" + encodeURIComponent(value);
    const stream = {
        id: "primary",
        type: "hls",
        playlist: requestUrl,
        flags: ["cors-allowed"],
        captions: []
    };
    return {
        embeds: [],
        stream: [stream]
    };
}
async function scrapeAetherShow(context) {
    const timestamp3 = { tmdbId: context.media.tmdbId, type: "show", season: context.media.season.number, episode: context.media.episode.number, timestamp: Date.now() };
    const value = aetherCreateToken(timestamp3);
    const requestUrl = aetherBaseUrl + "/tv/" + context.media.tmdbId + "/" + context.media.season.number + "/" + context.media.episode.number + "/master.m3u8?token=" + encodeURIComponent(value);
    const stream = {
        id: "primary",
        type: "hls",
        playlist: requestUrl,
        flags: ["cors-allowed"],
        captions: []
    };
    return {
        embeds: [],
        stream: [stream]
    };
}
const aetherProviderConfig = {
    id: "aether",
    name: "Aether-API \uD83D\uDD25",
    rank: 202,
    disabled: true,
    flags: ["cors-allowed"],
    scrapeMovie: scrapeAetherMovie,
    scrapeShow: scrapeAetherShow
};
const aetherProvider = createSourceProvider(aetherProviderConfig);
const aetherLatinoBaseUrl = "https://sol.aether.bar";
async function aetherLatinoResolveStream(context, language) {
    var temporaryValue;
    let value = "";
    context.media.type === "movie" ? value = aetherLatinoBaseUrl + "/movie/" + context.media.tmdbId + "?lang=" + language : value = aetherLatinoBaseUrl + "/tv/" + context.media.tmdbId + "/" + context.media.season.number + "/" + context.media.episode.number + "?lang=" + language;
    const result = {
        method: "GET"
    };
    const response = await context.fetcher(value, result);
    const url = (response?.streams) || [];
    const streams3 = [];
    for (const item of url)
        if (item.url && !(item.type
            === "mp4") &&
            item.type
                === "m3u8") {
            const match = (temporaryValue = item.server) == null ? void 0 : temporaryValue.match(/Server\s+(\d+)/i);
            const value4 = match ? match[1] : "1";
            const embed = {
                embedId: "aether-server-" + value4,
                url: item.url
            };
            streams3.push(embed);
        }
    return {
        embeds: streams3
    };
}
async function scrapeAetherLatinoMovie(context) {
    return aetherLatinoResolveStream(context, "lat");
}
async function scrapeAetherLatinoShow(context) {
    return aetherLatinoResolveStream(context, "lat");
}
async function scrapeAetherCastellanoMovie(context) {
    return aetherLatinoResolveStream(context, "esp");
}
async function scrapeAetherCastellanoShow(context) {
    return aetherLatinoResolveStream(context, "esp");
}
async function scrapeAetherSubtituladoMovie(context) {
    return aetherLatinoResolveStream(context, "sub");
}
async function scrapeAetherSubtituladoShow(context) {
    return aetherLatinoResolveStream(context, "sub");
}
const aetherLatinoSourceProvider = createSourceProvider({ id: "aether-latino", name: "Latino \uD83C\uDDEA\uD83C\uDDF8", rank: 887, disabled: false, flags: ["cors-allowed"], scrapeMovie: scrapeAetherLatinoMovie, scrapeShow: scrapeAetherLatinoShow });
const aetherCastellanoSourceProvider = createSourceProvider({ id: "aether-castellano", name: "Castellano \uD83C\uDDEA\uD83C\uDDF8", rank: 886, disabled: false, flags: ["cors-allowed"], scrapeMovie: scrapeAetherCastellanoMovie, scrapeShow: scrapeAetherCastellanoShow });
const aetherSubtituladoSourceProvider = createSourceProvider({ id: "aether-subtitulado", name: "Subtitulado \uD83C\uDDEA\uD83C\uDDF8", rank: 888, disabled: false, flags: ["cors-allowed"], scrapeMovie: scrapeAetherSubtituladoMovie, scrapeShow: scrapeAetherSubtituladoShow });
const cowflixBaseUrl = "https://cow.aether.bar";
async function scrapeCowflixMovie(context) {
    const result = {
        baseUrl: cowflixBaseUrl
    };
    const response = await context.fetcher("/movie/" + context.media.tmdbId, result);
    if (!response.stream_url) {
        throw new ScraperError("No stream found");
    }
    const stream = {
        id: "primary",
        type: "hls",
        playlist: response.stream_url,
        flags: ["cors-allowed"],
        captions: []
    };
    return {
        embeds: [],
        stream: [stream]
    };
}
async function scrapeCowflixShow(context) {
    const result = {
        baseUrl: cowflixBaseUrl
    };
    const response = await context.fetcher("/tv/" + context.media.tmdbId + "/" + context.media.season.number + "/" + context.media.episode.number, result);
    if (!response.stream_url) {
        throw new ScraperError("No stream found");
    }
    const stream = {
        id: "primary",
        type: "hls",
        playlist: response.stream_url,
        flags: ["cors-allowed"],
        captions: []
    };
    return {
        embeds: [],
        stream: [stream]
    };
}
const cowflixProviderConfig = {
    id: "cowflix",
    name: "Cowflix \uD83C\uDDE9\uD83C\uDDEA",
    rank: 885,
    disabled: false,
    flags: ["cors-allowed"],
    scrapeMovie: scrapeCowflixMovie,
    scrapeShow: scrapeCowflixShow
};
const cowflixProvider = createSourceProvider(cowflixProviderConfig);
const cowflixValue = {
    srt: "srt",
    vtt: "vtt"
};
const cowflixValue2 = cowflixValue;
function getSubtitleFileType(input) {
    const value = Object.keys(cowflixValue2);
    const item = value.find(item => input.endsWith("." + item));
    return item || null;
}
function normalizeLanguageCode(input) {
    const result = {
        "chinese - hong kong": "zh",
        "chinese - traditional": "zh",
        czech: "cs",
        danish: "da",
        dutch: "nl",
        english: "en",
        "english - sdh": "en",
        finnish: "fi",
        french: "fr",
        german: "de",
        greek: "el",
        hungarian: "hu",
        italian: "it",
        korean: "ko",
        norwegian: "no",
        polish: "pl",
        portuguese: "pt",
        "portuguese - brazilian": "pt",
        romanian: "ro",
        "spanish - european": "es",
        "spanish - latin american": "es",
        spanish: "es",
        swedish: "sv",
        turkish: "tr",
        "\u0627\u064E\u0644\u0652\u0639\u064E\u0631\u064E\u0628\u0650\u064A\u064E\u0651\u0629\u064F": "ar",
        "\u09AC\u09BE\u0982\u09B2\u09BE": "bn",
        filipino: "tl",
        indonesia: "id",
        "\u0627\u0631\u062F\u0648": "ur",
        English: "en",
        Arabic: "ar",
        Bosnian: "bs",
        Bulgarian: "bg",
        Croatian: "hr",
        Czech: "cs",
        Danish: "da",
        Dutch: "nl",
        Estonian: "et",
        Finnish: "fi",
        French: "fr",
        German: "de",
        Greek: "el",
        Hebrew: "he",
        Hungarian: "hu",
        Indonesian: "id",
        Italian: "it",
        Norwegian: "no",
        Persian: "fa",
        Polish: "pl",
        Portuguese: "pt",
        "Protuguese (BR)": "pt-br",
        Romanian: "ro",
        Russian: "ru",
        russian: "ru",
        Serbian: "sr",
        Slovenian: "sl",
        Spanish: "es",
        Swedish: "sv",
        Thai: "th",
        Turkish: "tr",
        ng: "en",
        re: "fr",
        pa: "es"
    };
    const value = result;
    const normalizedValue = value[input.toLowerCase()];
    if (normalizedValue) {
        return normalizedValue;
    }
    const value4 = gh.getCode(input);
    return value4.length
        ===
            0
        ? null : value4;
}
function isValidLanguageCode(input) {
    return input ? gh.validate(input) : false;
}
function deduplicateCaptionsByLanguage(input) {
    const result = {};
    return input.filter(item => {
        return result[item.language] ? false : (result[item.language] = true, true);
    });
}
function femapiProcessData() {
    try {
        if (typeof window === "undefined") {
            return "";
        }
        const value = window.localStorage.getItem("__MW::preferences");
        if (!value) {
            return "";
        }
        const data = JSON.parse(value);
        return (data?.state?.febboxKey) || "";
    }
    catch {
        return "";
    }
}
function femapiProcessData2() {
    try {
        if (typeof window === "undefined") {
            return null;
        }
        const value = window.localStorage.getItem("__MW::region");
        if (!value) {
            return null;
        }
        const data = JSON.parse(value);
        return (data?.state?.region) || null;
    }
    catch {
        return null;
    }
}
function femapiProcessData3() {
    return { uKbGM: function (argument1) {
            return argument1();
        } }.uKbGM(femapiProcessData).length > 0;
}
function femapiBuildUrl(input, argument2) {
    if (!argument2 || !Di[argument2]) {
        return input;
    }
    try {
        const value = Di[argument2];
        const parsedUrl = new URL(input);
        parsedUrl.hostname = value + ".shegu.net";
        return parsedUrl.toString();
    }
    catch {
        return input;
    }
}
const femapiBaseUrl = "https://fembox.aether.bar";
async function femapiResolveStream(context) {
    const value = femapiProcessData();
    const url = femapiProcessData2();
    const url3 = context.media.type === "movie" ? femapiBaseUrl + "/movie/" + context.media.tmdbId + "?ui=" + encodeURIComponent(value) : femapiBaseUrl + "/tv/" + context.media.tmdbId + "/" + context.media.season.number + "/" + context.media.episode.number + "?ui=" + encodeURIComponent(value);
    const requestOptions = {
        Origin: "https://lordflix.club",
        Referer: "https://lordflix.club"
    };
    const requestOptions2 = {
        headers: requestOptions
    };
    const response = await context.fetcher(url3, requestOptions2);
    if (!(response != null && response.sources) || response.sources.length === 0) {
        throw new ScraperError("No stream found");
    }
    context.progress(50);
    const result = {};
    for (const streamItem of response.sources) {
        if (!streamItem.url || !streamItem.quality) {
            continue;
        }
        const url4 = W[streamItem.quality];
        if (url4) {
            (result[url4] = femapiBuildUrl(streamItem.url, url));
        }
    }
    if (Object.keys(result).length
        ===
            0) {
        throw new ScraperError("No valid streams found");
    }
    const captions = [];
    if (response.subtitles) {
        for (const track of response.subtitles) {
            const language = normalizeLanguageCode(track.language);
            if (language) {
                const caption = {
                    id: track.url,
                    url: track.url,
                    type: "srt",
                    language: language,
                    hasCorsRestrictions: false
                };
                captions.push(caption);
            }
        }
    }
    context.progress(90);
    const stream = {
        id: "primary",
        captions: captions,
        qualities: { ...result[2160] && { "4k": { type: "mp4", url: result[2160] } }, ...result[1080] && { 1080: { type: "mp4", url: result[1080] } }, ...result[720] && { 720: { type: "mp4", url: result[720] } }, ...result[480] && { 480: { type: "mp4", url: result[480] } }, ...result[360] && { 360: { type: "mp4", url: result[360] } }, ...result.unknown && { unknown: { type: "mp4", url: result.unknown } } },
        type: "file",
        flags: ["cors-allowed"]
    };
    return {
        embeds: [],
        stream: [stream]
    };
}
function femapiHlsProcessData() {
    try {
        if (typeof window === "undefined") {
            return "";
        }
        const value = window.localStorage.getItem("__MW::preferences");
        if (!value) {
            return "";
        }
        const data = JSON.parse(value);
        return (data?.state?.febboxKey) || "";
    }
    catch {
        return "";
    }
}
function femapiHlsProcessData2() {
    return femapiHlsProcessData().length > 0;
}
const femapiSourceProvider = createSourceProvider({ id: "femapi", name: "FEM MP4 (4K) \uD83D\uDD25", rank: 67676766, disabled: !femapiProcessData3(), flags: ["cors-allowed"], scrapeMovie: femapiResolveStream, scrapeShow: femapiResolveStream });
const femapiHlsBaseUrl = "https://fembox.aether.bar";
async function femapiHlsResolveStream(context) {
    const value = femapiHlsProcessData();
    const url = context.media.type === "movie" ? femapiHlsBaseUrl + "/hls/movie/" + context.media.tmdbId + "?ui=" + encodeURIComponent(value) : femapiHlsBaseUrl + "/hls/tv/" + context.media.tmdbId + "/" + context.media.season.number + "/" + context.media.episode.number + "?ui=" + encodeURIComponent(value);
    const response = await context.fetcher(url);
    if (!(response != null && response.hls)) {
        throw new ScraperError("No stream found");
    }
    const captions = [];
    if (response.subtitles) {
        for (const track of response.subtitles) {
            const language = normalizeLanguageCode(track.language);
            if (language) {
                const caption = {
                    id: track.url,
                    url: track.url,
                    type: "srt",
                    language: language,
                    hasCorsRestrictions: false
                };
                captions.push(caption);
            }
        }
    }
    const stream = {
        id: "primary",
        captions: captions,
        playlist: response.hls,
        type: "hls",
        flags: ["cors-allowed"]
    };
    return {
        embeds: [],
        stream: [stream]
    };
}
const femapiHlsSourceProvider = createSourceProvider({ id: "femapi-hls", name: "FEM HLS (4K) \uD83D\uDD25", rank: 67676767, disabled: !femapiHlsProcessData2(), flags: ["cors-allowed"], scrapeMovie: femapiHlsResolveStream, scrapeShow: femapiHlsResolveStream });
const femexpBaseUrl = "https://easy.aether.cx";
function femexpProcessData(context) {
    const value = context.media.type === "movie" ? "movie/" + context.media.tmdbId : "tv/" + context.media.tmdbId + "/" + context.media.season.number + "/" + context.media.episode.number;
    return femexpBaseUrl + "/" + value + "?provider=jett&single=1";
}
function femexpMapQuality(input) {
    const value = (input == null ? void 0 : input.toLowerCase()) ?? "";
    if (value.includes("4k") || value.includes("2160")) {
        return 2160;
    }
    const match = value.match(/(\d{3,4})/u);
    return match ?
        Number(match[1])
        : 0;
}
async function scrapeFemexp(context) {
    const response = await context.fetcher(femexpProcessData(context));
    let temporaryValue;
    if (typeof response !== "string") {
        temporaryValue = response;
    }
    else {
        try {
            temporaryValue = JSON.parse(response);
        }
        catch {
            throw new ScraperError("FEM EXP API returned a non-JSON response");
        }
    }
    const value = new Set;
    const value3 = new Set;
    const streams = [];
    if ((temporaryValue.sources ?? []).filter(item => typeof item.url == "string" && item.url.includes(".m3u8")).sort((left, right) => femexpMapQuality(right.quality) - femexpMapQuality(left.quality)).forEach(item => {
        const url = item.url;
        if (value.has(url))
            return;
        value.add(url);
        const value = mapFemexpJettQuality(item.quality);
        if (!value || value3.has(value))
            return;
        value3.add(value);
        const result = {};
        result.embedId = value, result.url = url, streams.push(result);
    }),
        streams.length
            ===
                0) {
        throw new ScraperError("No FEM EXP streams found");
    }
    return {
        embeds: streams
    };
}
const femexpProviderConfig = {
    id: "femexp",
    name: "FEM EXP \uD83D\uDD25",
    rank: 920,
    disabled: true,
    flags: ["cors-allowed"],
    scrapeMovie: scrapeFemexp,
    scrapeShow: scrapeFemexp
};
const femexpProvider = createSourceProvider(femexpProviderConfig);
const gallicBaseUrl = "https://baguette.aether.cx";
const gallicValue = "vidzy";
async function gallicResolveStream(context, argument2) {
    var temporaryValue;
    try {
        const value = "" + gallicBaseUrl + argument2;
        const response = await context.fetcher(value);
        const item = (temporaryValue = response?.streams) == null ? void 0 : temporaryValue.find(item => item.host === gallicValue);
        if (item != null && item.url) {
            return item.url;
        }
    }
    catch {
    }
    throw new ScraperError("No stream found");
}
async function scrapeGallicMovie(context) {
    const requestUrl = "/api/movie/" + context.media.tmdbId;
    const value = await gallicResolveStream(context, requestUrl);
    const stream = {
        id: "primary",
        type: "hls",
        playlist: value,
        flags: ["cors-allowed"],
        captions: []
    };
    return {
        embeds: [],
        stream: [stream]
    };
}
async function scrapeGallicShow(context) {
    const requestUrl = "/api/tv/" + context.media.tmdbId + "?s=" + context.media.season.number + "&e=" + context.media.episode.number;
    const value = await gallicResolveStream(context, requestUrl);
    const stream = {
        id: "primary",
        type: "hls",
        playlist: value,
        flags: ["cors-allowed"],
        captions: []
    };
    return {
        embeds: [],
        stream: [stream]
    };
}
const gallicProviderConfig = {
    id: "gallic",
    name: "Gallic \uD83C\uDDEB\uD83C\uDDF7",
    rank: 878,
    flags: ["cors-allowed"],
    scrapeMovie: scrapeGallicMovie,
    scrapeShow: scrapeGallicShow
};
const gallicProvider = createSourceProvider(gallicProviderConfig);
const linkBaseUrl = "https://link.aether.cx";
async function scrapeLink(context) {
    const tmdbId2 = context.media.tmdbId;
    let temporaryValue;
    context.media.type === "movie" ? temporaryValue = linkBaseUrl + "/movie/" + tmdbId2 : temporaryValue = linkBaseUrl + "/tv/" + tmdbId2 + "/" + context.media.season.number + "/" + context.media.episode.number;
    const response = await context.fetcher(temporaryValue);
    if (!response.stream) {
        throw new ScraperError("No stream found");
    }
    const stream = {
        id: "link-0",
        type: "hls",
        playlist: response.stream,
        flags: ["cors-allowed"],
        captions: []
    };
    return {
        stream: [stream],
        embeds: []
    };
}
const linkProviderConfig = {
    id: "link",
    name: "Link \uD83D\uDD17",
    rank: 916,
    disabled: false,
    flags: ["cors-allowed"],
    scrapeMovie: scrapeLink,
    scrapeShow: scrapeLink
};
const linkProvider = createSourceProvider(linkProviderConfig);
const lulBaseUrl = "https://lul.aether.cx";
async function scrapeLul(context) {
    const tmdbId2 = context.media.tmdbId;
    let temporaryValue;
    context.media.type === "movie" ? temporaryValue = lulBaseUrl + "/movie/" + tmdbId2 : temporaryValue = lulBaseUrl + "/tv/" + tmdbId2 + "/" + context.media.season.number + "/" + context.media.episode.number;
    const response = await context.fetcher(temporaryValue);
    const value = response.stream_url || response.stream;
    if (!value) {
        throw new ScraperError("No stream found");
    }
    const stream = {
        id: "lul-0",
        type: "hls",
        playlist: value,
        flags: ["cors-allowed"],
        captions: []
    };
    const captions = [stream];
    return {
        stream: captions,
        embeds: []
    };
}
const lulProviderConfig = {
    id: "lul",
    name: "Lul \uD83D\uDC7E",
    rank: 917,
    disabled: false,
    flags: ["cors-allowed"],
    scrapeMovie: scrapeLul,
    scrapeShow: scrapeLul
};
const lulProvider = createSourceProvider(lulProviderConfig);
function meridianNormalizeLanguage(input) {
    if (!input || !Array.isArray(input)) {
        return [];
    }
    const language = input.map(item => {
        const language = normalizeLanguageCode(item.language);
        if (!language) {
            return null;
        }
        return {
            id: item.url,
            url: item.url,
            type: item.type === "vtt" ? "vtt" : "srt",
            language: language,
            hasCorsRestrictions: false
        };
    }).filter(item => item !== null);
    return deduplicateCaptionsByLanguage(language);
}
async function scrapeMeridianMovie(context) {
    let temporaryValue;
    try {
        const result = {
            method: "GET"
        };
        temporaryValue = await context.fetcher("https://meridian.aether.bar/movie/" + context.media.tmdbId, result);
    }
    catch {
        throw new ScraperError("No stream found");
    }
    if (!temporaryValue || !temporaryValue.url) {
        throw new ScraperError("No stream found");
    }
    const value = meridianNormalizeLanguage(temporaryValue.subtitles);
    const stream = {
        id: "primary",
        type: "hls",
        playlist: temporaryValue.url,
        flags: ["cors-allowed"],
        captions: value
    };
    return {
        embeds: [],
        stream: [stream]
    };
}
async function scrapeMeridianShow(context) {
    let temporaryValue;
    try {
        const result = {
            method: "GET"
        };
        temporaryValue = await context.fetcher("https://meridian.aether.bar/show/" + context.media.tmdbId + "/" + context.media.season.number + "/" + context.media.episode.number, result);
    }
    catch {
        throw new ScraperError("No stream found");
    }
    if (!temporaryValue || !temporaryValue.url) {
        throw new ScraperError("No stream found");
    }
    const value = meridianNormalizeLanguage(temporaryValue.subtitles);
    const stream = {
        id: "primary",
        type: "hls",
        playlist: temporaryValue.url,
        flags: ["cors-allowed"],
        captions: value
    };
    return {
        embeds: [],
        stream: [stream]
    };
}
const meridianProviderConfig = {
    id: "meridian",
    name: "Meridian \uD83E\uDE90",
    rank: 912,
    flags: ["cors-allowed"],
    disabled: false,
    scrapeMovie: scrapeMeridianMovie,
    scrapeShow: scrapeMeridianShow
};
const meridianProvider = createSourceProvider(meridianProviderConfig);
const nebulaBaseUrl = "https://nebula.aether.cx";
async function scrapeNebula(context) {
    var temporaryValue;
    const tmdbId2 = context.media.tmdbId;
    let url;
    context.media.type === "movie" ? url = nebulaBaseUrl + "/movie/" + tmdbId2 + "?ser=cf" : url = nebulaBaseUrl + "/tv/" + tmdbId2 + "/" + context.media.season.number + "/" + context.media.episode.number + "?ser=cf";
    const response = await context.fetcher(url);
    const items = ((temporaryValue = response.streams) == null ? void 0 : temporaryValue.filter(item => item.type === "hls" && item.url).map((item, index) => ({ id: "nebula-" + index, type: "hls", playlist: item.url, flags: ["cors-allowed"], captions: [] }))) ?? [];
    if (items.length === 0) {
        throw new ScraperError("No stream found");
    }
    return {
        stream: items,
        embeds: []
    };
}
const nebulaProviderConfig = {
    id: "nebula",
    name: "Nebula \uD83C\uDF0C",
    rank: 913,
    disabled: false,
    flags: ["cors-allowed"],
    scrapeMovie: scrapeNebula,
    scrapeShow: scrapeNebula
};
const nebulaProvider = createSourceProvider(nebulaProviderConfig);
const onionBaseUrl = "https://on.aether.bar";
async function scrapeOnionMovie(context) {
    const result = {
        baseUrl: onionBaseUrl
    };
    const response = await context.fetcher("/movie/" + context.media.tmdbId, result);
    if (!response || !response.success || !response.streamUrl) {
        throw new ScraperError("No stream found");
    }
    const stream = {
        id: "primary",
        type: "hls",
        playlist: response.streamUrl,
        flags: ["cors-allowed"],
        captions: []
    };
    return {
        embeds: [],
        stream: [stream]
    };
}
async function scrapeOnionShow(context) {
    const result = {
        baseUrl: onionBaseUrl
    };
    const response = await context.fetcher("/tv/" + context.media.tmdbId + "/" + context.media.season.number + "/" + context.media.episode.number, result);
    if (!response || !response.success || !response.streamUrl) {
        throw new ScraperError("No stream found");
    }
    const stream = {
        id: "primary",
        type: "hls",
        playlist: response.streamUrl,
        flags: ["cors-allowed"],
        captions: []
    };
    return {
        embeds: [],
        stream: [stream]
    };
}
const onionProviderConfig = {
    id: "onion",
    name: "Onion \uD83E\uDDC5",
    rank: 883,
    disabled: true,
    flags: ["cors-allowed"],
    scrapeMovie: scrapeOnionMovie,
    scrapeShow: scrapeOnionShow
};
const onionProvider = createSourceProvider(onionProviderConfig);
const tikiServerUrls = ["https://tiki.aether.cx"];
async function scrapeTiki(context) {
    const tmdbId2 = context.media.tmdbId;
    for (const item of tikiServerUrls) {
        let temporaryValue;
        if (context.media.type === "movie") {
            temporaryValue = item + "/movie/" + tmdbId2;
        }
        else {
            temporaryValue = item + "/tv/" + tmdbId2 + "/" + context.media.season.number + "/" + context.media.episode.number;
        }
        try {
            const response = await context.fetcher(temporaryValue);
            if (response.stream) {
                return { stream: [{ id: "tiki", type: "hls", playlist: buildProxiedHlsUrl(response.stream, context.features), flags: ["cors-allowed"], captions: [] }], embeds: [] };
            }
        }
        catch {
            continue;
        }
    }
    throw new ScraperError("No stream found");
}
const tikiProviderConfig = {
    id: "tiki",
    name: "Tiki \uD83D\uDDFF",
    rank: 911,
    disabled: false,
    flags: ["cors-allowed"],
    scrapeMovie: scrapeTiki,
    scrapeShow: scrapeTiki
};
const tikiProvider = createSourceProvider(tikiProviderConfig);
const vidyBaseUrl = "https://vidy.aether.cx";
async function scrapeVidy(context) {
    const tmdbId2 = context.media.tmdbId;
    let temporaryValue;
    context.media.type === "movie" ? temporaryValue = vidyBaseUrl + "/movie/" + tmdbId2 : temporaryValue = vidyBaseUrl + "/tv/" + tmdbId2 + "/" + context.media.season.number + "/" + context.media.episode.number;
    const response = await context.fetcher(temporaryValue);
    if (!response.stream) {
        throw new ScraperError("No stream found");
    }
    const playlistUrl = buildProxiedHlsUrl(response.stream, context.features);
    const stream = {
        id: "vidy-0",
        type: "hls",
        playlist: playlistUrl,
        flags: ["cors-allowed"],
        captions: []
    };
    return {
        stream: [stream],
        embeds: []
    };
}
const vidyProviderConfig = {
    id: "vidy",
    name: "Vidy \uD83D\uDCFA",
    rank: 910,
    disabled: false,
    flags: ["cors-allowed"],
    scrapeMovie: scrapeVidy,
    scrapeShow: scrapeVidy
};
const vidyProvider = createSourceProvider(vidyProviderConfig);
const vixsrcServerUrls = ["https://vix.aether.bar", "https://vix2.aether.bar", "https://vix3.aether.bar", "https://vix4.aether.bar", "https://vix5.aether.bar", "https://vix6.aether.bar"];
async function vixsrcResolveStream(context, argument2) {
    const value = [...vixsrcServerUrls].sort(() => Math.random() - 0.5);
    for (const item of value)
        try {
            const value3 = "" + item + argument2;
            const response = await context.fetcher(value3);
            if (response && response.streamUrl) {
                return response;
            }
        }
        catch {
            continue;
        }
    throw new ScraperError("No stream found across all APIs");
}
function vixsrcNormalizeLanguage(input) {
    return input ? input.map(item => {
        const parts = item.name.split(" ")[0];
        return { id: item.url, url: item.url, type: "vtt", hasCorsRestrictions: false, language: normalizeLanguageCode(parts) || item.language };
    }) : [];
}
async function scrapeVixsrcMovie(context) {
    const requestUrl = "/movie/" + context.media.tmdbId;
    const value = await vixsrcResolveStream(context, requestUrl);
    return { embeds: [], stream: [{ id: "primary", type: "hls", playlist: value.streamUrl, flags: ["cors-allowed"], captions: vixsrcNormalizeLanguage(value.subtitles) }] };
}
async function scrapeVixsrcShow(context) {
    const requestUrl = "/tv/" + context.media.tmdbId + "/" + context.media.season.number + "/" + context.media.episode.number;
    const value = await vixsrcResolveStream(context, requestUrl);
    return { embeds: [], stream: [{ id: "primary", type: "hls", playlist: value.streamUrl, flags: ["cors-allowed"], captions: vixsrcNormalizeLanguage(value.subtitles) }] };
}
const vixsrcProviderConfig = {
    id: "vixsrc",
    name: "VixSrc \uD83C\uDDEE\uD83C\uDDF9",
    rank: 879,
    disabled: true,
    flags: ["cors-allowed"],
    scrapeMovie: scrapeVixsrcMovie,
    scrapeShow: scrapeVixsrcShow
};
const vixsrcProvider = createSourceProvider(vixsrcProviderConfig);
const yakamozBaseUrl = "https://tr.aether.bar";
const yakamozValue = "telaviv133";
async function scrapeYakamozMovie(context) {
    const timestamp = Date.now();
    const value = "" + context.media.tmdbId + timestamp + yakamozValue;
    const signature = CryptoJS.SHA256(value).toString(CryptoJS.enc.Hex);
    const embed = {
        embedId: "yakamoz-dublaj",
        url: yakamozBaseUrl + "/movie/" + context.media.tmdbId + "?dil=0&t=" + timestamp + "&h=" + signature
    };
    const embed3 = {
        embedId: "yakamoz-altyazi",
        url: yakamozBaseUrl + "/movie/" + context.media.tmdbId + "?dil=1&t=" + timestamp + "&h=" + signature
    };
    return {
        embeds: [embed, embed3]
    };
}
async function scrapeYakamozShow(context) {
    const timestamp = Date.now();
    const value = "" + context.media.tmdbId + context.media.season.number + context.media.episode.number + timestamp + yakamozValue;
    const signature = CryptoJS.SHA256(value).toString(CryptoJS.enc.Hex);
    const embed = {
        embedId: "yakamoz-dublaj",
        url: yakamozBaseUrl + "/show/" + context.media.tmdbId + "/season/" + context.media.season.number + "/episode/" + context.media.episode.number + "?dil=0&t=" + timestamp + "&h=" + signature
    };
    const embed3 = {
        embedId: "yakamoz-altyazi",
        url: yakamozBaseUrl + "/show/" + context.media.tmdbId + "/season/" + context.media.season.number + "/episode/" + context.media.episode.number + "?dil=1&t=" + timestamp + "&h=" + signature
    };
    return {
        embeds: [embed, embed3]
    };
}
const yakamozProviderConfig = {
    id: "yakamoz",
    name: "Yakamoz \uD83C\uDDF9\uD83C\uDDF7",
    rank: 206,
    disabled: true,
    flags: ["cors-allowed"],
    scrapeMovie: scrapeYakamozMovie,
    scrapeShow: scrapeYakamozShow
};
const yakamozProvider = createSourceProvider(yakamozProviderConfig);
const providersSkippingValidation = [...aetherServerEmbedProviders.map(item => item.id), ...videasyCdnEmbedProviders.map(item => item.id), ...femexpJettEmbedProviders.map(item => item.id), warezcdnembedmp4EmbedProvider.id, femapiSourceProvider.id, femapiHlsSourceProvider.id, femexpProvider.id, aetherProvider.id, nebulaProvider.id, lulProvider.id, linkProvider.id, vidyProvider.id, cowflixProvider.id, aetherLatinoSourceProvider.id, aetherCastellanoSourceProvider.id, aetherSubtituladoSourceProvider.id, tikiProvider.id, onionProvider.id, vixsrcProvider.id, gallicProvider.id, meridianProvider.id, yakamozProvider.id, yakamozDublajEmbedProvider.id, yakamozAltyaziEmbedProvider.id];
const sourcesUsingDirectFetch = [bombtheirishProvider.id];
function isUsableStream(stream) {
    if (!stream) {
        return false;
    }
    if (stream.type === "hls") {
        return Boolean(stream.playlist);
    }
    if (stream.type === "file") {
        return Object.values(stream.qualities).some(item => item.url.length > 0);
    }
    return false;
}
function isAlreadyProxiedUrl(input) {
    return input.includes("/m3u8-proxy?url=");
}
async function validateStreamUrl(stream, runtime, providerId) {
    if (providersSkippingValidation.includes(providerId)) {
        return stream;
    }
    const useDirectFetch = sourcesUsingDirectFetch.includes(providerId);
    const requestHeaders = {
        ...stream.preferredHeaders,
        ...stream.headers
    };
    if (stream.type === "hls") {
        if (stream.playlist.startsWith("data:")) {
            return stream;
        }
        let response;
        if (useDirectFetch || isAlreadyProxiedUrl(stream.playlist)) {
            try {
                const fetchResponse = await fetch(stream.playlist, {
                    method: "GET",
                    headers: requestHeaders
                });
                response = {
                    statusCode: fetchResponse.status,
                    body: await fetchResponse.text(),
                    finalUrl: fetchResponse.url
                };
            }
            catch {
                return null;
            }
        }
        else {
            response = await runtime.proxiedFetcher.full(stream.playlist, {
                method: "GET",
                headers: requestHeaders
            });
        }
        return response.statusCode >= 200 && response.statusCode < 400
            ? stream
            : null;
    }
    if (stream.type === "file") {
        const qualities = stream.qualities;
        const qualityEntries = Object.entries(qualities);
        const responses = await Promise.all(qualityEntries.map(async ([, quality]) => {
            const rangeHeaders = {
                ...requestHeaders,
                Range: "bytes=0-1"
            };
            if (useDirectFetch || isAlreadyProxiedUrl(quality.url)) {
                try {
                    const fetchResponse = await fetch(quality.url, {
                        method: "GET",
                        headers: rangeHeaders
                    });
                    return {
                        statusCode: fetchResponse.status,
                        body: await fetchResponse.text(),
                        finalUrl: fetchResponse.url
                    };
                }
                catch {
                    return {
                        statusCode: 500,
                        body: "",
                        finalUrl: quality.url
                    };
                }
            }
            return runtime.proxiedFetcher.full(quality.url, {
                method: "GET",
                headers: rangeHeaders
            });
        }));
        qualityEntries.forEach(([qualityName], index) => {
            const status = responses[index].statusCode;
            if (status < 200 || status >= 400) {
                delete qualities[qualityName];
            }
        });
        return Object.keys(qualities).length > 0
            ? { ...stream, qualities }
            : null;
    }
    return null;
}
async function validateStreamList(streams, runtime, providerId) {
    if (providersSkippingValidation.includes(providerId)) {
        return streams;
    }
    const validatedStreams = await Promise.all(streams.map(item => validateStreamUrl(item, runtime, providerId)));
    return validatedStreams.filter(item => item !== null);
}
async function runSourceScraperById(context, options) {
    const provider = context.sources.find(item => item.id === options.id);
    if (!provider) {
        throw new Error("Source with ID not found");
    }
    if (options.media.type === "movie" && !provider.scrapeMovie) {
        throw new Error("Source is not compatible with movies");
    }
    if (options.media.type === "show" && !provider.scrapeShow) {
        throw new Error("Source is not compatible with shows");
    }
    const scraperContext = {
        fetcher: options.fetcher,
        proxiedFetcher: options.proxiedFetcher,
        features: options.features,
        progress(percentage) {
            options.events?.update?.({
                id: provider.id,
                percentage,
                status: "pending"
            });
        }
    };
    let output;
    if (options.media.type === "movie") {
        output = await provider.scrapeMovie({
            ...scraperContext,
            media: options.media
        });
    }
    else {
        output = await provider.scrapeShow({
            ...scraperContext,
            media: options.media
        });
    }
    if (!output) {
        throw new Error("output is null");
    }
    output.stream = (output.stream ?? [])
        .filter(isUsableStream)
        .filter(item => supportsRequiredFlags(options.features, item.flags))
        .map(item => streamRequiresProxy(item) && options.proxyStreams
        ? proxyStreamUrls(item)
        : item);
    output.embeds = (output.embeds ?? []).filter(item => {
        const embedProvider = context.embeds.find(embed => embed.id === item.embedId);
        return Boolean(embedProvider && !embedProvider.disabled);
    });
    if (output.stream.length === 0 && output.embeds.length === 0) {
        throw new ScraperError("No streams found");
    }
    if (output.stream.length > 0 && output.embeds.length === 0) {
        output.stream = await validateStreamList(output.stream, options, provider.id);
        if (output.stream.length === 0) {
            throw new ScraperError("No playable streams found");
        }
    }
    return output;
}
async function runEmbedScraperById(context, options) {
    const provider = context.embeds.find(item => item.id === options.id);
    if (!provider) {
        throw new Error("Embed with ID not found");
    }
    const output = await provider.scrape({
        fetcher: options.fetcher,
        proxiedFetcher: options.proxiedFetcher,
        features: options.features,
        url: options.url,
        progress(percentage) {
            options.events?.update?.({
                id: provider.id,
                percentage,
                status: "pending"
            });
        }
    });
    output.stream = output.stream
        .filter(isUsableStream)
        .filter(item => supportsRequiredFlags(options.features, item.flags))
        .map(item => streamRequiresProxy(item) && options.proxyStreams
        ? proxyStreamUrls(item)
        : item);
    if (output.stream.length === 0) {
        throw new ScraperError("No streams found");
    }
    output.stream = await validateStreamList(output.stream, options, provider.id);
    if (output.stream.length === 0) {
        throw new ScraperError("No playable streams found");
    }
    return output;
}
function sortProvidersByPreference(preferredIds, providers) {
    return [...providers].sort((left, right) => {
        const leftPreference = preferredIds.indexOf(left.id);
        const rightPreference = preferredIds.indexOf(right.id);
        if (leftPreference >= 0 && rightPreference >= 0) {
            return leftPreference - rightPreference;
        }
        if (rightPreference >= 0) {
            return 1;
        }
        if (leftPreference >= 0) {
            return -1;
        }
        return right.rank - left.rank;
    });
}
async function runFirstWorkingScraper(registry, options) {
    const sourceProviders = sortProvidersByPreference(options.sourceOrder ?? [], registry.sources).filter(item => options.media.type === "movie"
        ? Boolean(item.scrapeMovie)
        : Boolean(item.scrapeShow));
    const embedProviders = sortProvidersByPreference(options.embedOrder ?? [], registry.embeds);
    const embedOrder = embedProviders.map(item => item.id);
    let activeTaskId = "";
    const scraperContext = {
        fetcher: options.fetcher,
        proxiedFetcher: options.proxiedFetcher,
        features: options.features,
        progress(percentage) {
            options.events?.update?.({
                id: activeTaskId,
                percentage,
                status: "pending"
            });
        }
    };
    options.events?.init?.({ sourceIds: sourceProviders.map(item => item.id) });
    for (const sourceProvider of sourceProviders) {
        options.events?.start?.(sourceProvider.id);
        activeTaskId = sourceProvider.id;
        let sourceOutput;
        try {
            sourceOutput = options.media.type === "movie"
                ? await sourceProvider.scrapeMovie({ ...scraperContext, media: options.media })
                : await sourceProvider.scrapeShow({ ...scraperContext, media: options.media });
            if (!sourceOutput) {
                throw new ScraperError("No streams found");
            }
            sourceOutput.stream = (sourceOutput.stream ?? [])
                .filter(isUsableStream)
                .filter(item => supportsRequiredFlags(options.features, item.flags))
                .map(item => streamRequiresProxy(item) && options.proxyStreams
                ? proxyStreamUrls(item)
                : item);
            if (sourceOutput.stream.length === 0 && sourceOutput.embeds.length === 0) {
                throw new ScraperError("No streams found");
            }
        }
        catch (error) {
            options.events?.update?.({
                id: sourceProvider.id,
                percentage: 100,
                status: error instanceof ScraperError ? "notfound" : "failure",
                reason: error instanceof ScraperError ? error.message : undefined,
                error: error instanceof ScraperError ? undefined : error
            });
            continue;
        }
        if (sourceOutput.stream?.[0]) {
            const stream = await validateStreamUrl(sourceOutput.stream[0], options, sourceProvider.id);
            if (!stream) {
                throw new ScraperError("No streams found");
            }
            return { sourceId: sourceProvider.id, stream };
        }
        const embeds = sourceOutput.embeds
            .filter(item => {
            const provider = registry.embeds.find(embed => embed.id === item.embedId);
            return Boolean(provider && !provider.disabled);
        })
            .sort((left, right) => embedOrder.indexOf(left.embedId) - embedOrder.indexOf(right.embedId));
        if (embeds.length > 0) {
            options.events?.discoverEmbeds?.({
                embeds: embeds.map((item, index) => ({
                    id: `${sourceProvider.id}-${index}`,
                    embedScraperId: item.embedId
                })),
                sourceId: sourceProvider.id
            });
        }
        for (const [embedIndex, embed] of embeds.entries()) {
            const embedProvider = embedProviders.find(item => item.id === embed.embedId);
            if (!embedProvider) {
                throw new Error("Invalid embed returned");
            }
            const taskId = `${sourceProvider.id}-${embedIndex}`;
            options.events?.start?.(taskId);
            activeTaskId = taskId;
            try {
                const embedOutput = await embedProvider.scrape({
                    ...scraperContext,
                    url: embed.url
                });
                embedOutput.stream = embedOutput.stream
                    .filter(isUsableStream)
                    .filter(item => supportsRequiredFlags(options.features, item.flags))
                    .map(item => streamRequiresProxy(item) && options.proxyStreams
                    ? proxyStreamUrls(item)
                    : item);
                if (embedOutput.stream.length === 0) {
                    throw new ScraperError("No streams found");
                }
                const stream = await validateStreamUrl(embedOutput.stream[0], options, embed.embedId);
                if (!stream) {
                    throw new ScraperError("No streams found");
                }
                return {
                    sourceId: sourceProvider.id,
                    embedId: embedProvider.id,
                    stream
                };
            }
            catch (error) {
                options.events?.update?.({
                    id: taskId,
                    percentage: 100,
                    status: error instanceof ScraperError ? "notfound" : "failure",
                    reason: error instanceof ScraperError ? error.message : undefined,
                    error: error instanceof ScraperError ? undefined : error
                });
            }
        }
    }
    return null;
}
function createScraperRunner(configuration) {
    const registry = {
        embeds: configuration.embeds,
        sources: configuration.sources
    };
    const defaults = {
        features: configuration.features,
        fetcher: normalizeFetcher(configuration.fetcher),
        proxiedFetcher: normalizeFetcher(configuration.proxiedFetcher ?? configuration.fetcher),
        proxyStreams: configuration.proxyStreams
    };
    return {
        runAll(options) {
            return runFirstWorkingScraper(registry, { ...defaults, ...options });
        },
        runSourceScraper(options) {
            return runSourceScraperById(registry, { ...defaults, ...options });
        },
        runEmbedScraper(options) {
            return runEmbedScraperById(registry, { ...defaults, ...options });
        },
        getMetadata(providerId) {
            return getProviderMetadata(registry, providerId);
        },
        listSources() {
            return listSourceMetadata(registry);
        },
        listEmbeds() {
            return listEmbedMetadata(registry);
        }
    };
}
const akcloudBaseUrl = "https://videostr.net";
const akcloudPatterns = [/<div data-dpi="([^"]+)" style="display:none">/, /<meta name="_gg_fb" content="([^"]+)">/, /<!-- _is_th:([^ ]+) -->/, /window\._xy_ws = "([^"]+)"/, /nonce="([^"]+)"/, /window\._lk_db = {x: "([^"]+)", y: "([^"]+)", z: "([^"]+)"}/];
function akcloudExtractValue(text) {
    for (const item of akcloudPatterns) {
        const match = text.match(item);
        if (match) {
            return match.length
                ===
                    4
                ? "" + match[1] + match[2] + match[3] : match[1];
        }
    }
    return null;
}
async function scrapeAkcloud(context) {
    const response = await context.proxiedFetcher(context.url, { headers: { Referer: context.url } });
    const document = loadHtml(response);
    const dataId = document("#megacloud-player").attr("data-id");
    if (!dataId) {
        throw new ScraperError("Could not find data-id");
    }
    const extractedKey = akcloudExtractValue(response);
    if (!extractedKey) {
        throw new ScraperError("Could not find k-value");
    }
    const sourcesUrl = akcloudBaseUrl + "/embed-1/v3/e-1/getSources?id=" + dataId + "&_k=" + extractedKey;
    const sourcesResponse = await context.proxiedFetcher(sourcesUrl, { headers: { "X-Requested-With": "XMLHttpRequest", Referer: context.url } });
    if (!sourcesResponse.sources) {
        throw new ScraperError("No sources found");
    }
    const captions = [];
    if (sourcesResponse.tracks) {
        for (const track of sourcesResponse.tracks) {
            const language = normalizeLanguageCode(track.label);
            const subtitleType = getSubtitleFileType(track.file);
            if (!language
                ||
                    !subtitleType) {
                continue;
            }
            const caption = {
                id: track.file,
                url: track.file,
                language: language,
                type: subtitleType,
                hasCorsRestrictions: false
            };
            captions.push(caption);
        }
    }
    const requestOptions = {
        Referer: "https://videosrt.net/"
    };
    const value = requestOptions;
    const playlistUrl = buildProxiedHlsUrl(sourcesResponse.sources[0].file, context.features, value);
    const stream = {
        id: "primary",
        playlist: playlistUrl,
        type: "hls",
        flags: ["cors-allowed"],
        captions: captions,
        headers: value
    };
    return {
        stream: [stream]
    };
}
const akcloudEmbedProvider = createEmbedProvider({ id: "akcloud", name: "AKCloud", rank: 202, scrape: scrapeAkcloud });
const diziyouEnValue = {
    id: "diziyou-en",
    name: "Kl (EN)",
    rank: 162
};
const diziyouEnEmbedProvider = createEmbedProvider(diziyouEnValue);
const diziyouTrValue = {
    id: "diziyou-tr",
    name: "Kl (TR)",
    rank: 161
};
async function scrapeDood(context) {
    let url = context.url;
    if (context.url.includes("primewire")) {
        (url = (await context.proxiedFetcher.full(context.url)).finalUrl);
    }
    const mediaId = url.split("/d/")[1] || url.split("/e/")[1];
    const result = {
        method: "GET",
        baseUrl: doodBaseUrl
    };
    const response = await context.proxiedFetcher("/e/" + mediaId, result);
    const videoUrl = response.match(/\?token=([^&]+)&expiry=/)?.[1];
    const passPath = response.match(/\$\.get\('\/pass_md5([^']+)/)?.[1];
    const thumbnailMatch = response.match(/thumbnails:\s\{\s*vtt:\s'([^']*)'/);
    const requestOptions = {
        Referer: doodBaseUrl + "/e/" + mediaId
    };
    const requestOptions2 = {
        headers: requestOptions,
        method: "GET",
        baseUrl: doodBaseUrl
    };
    const response2 = await context.proxiedFetcher("/pass_md5" + passPath, requestOptions2);
    const timestamp = "" + response2 + doodValue() + "?token=" + videoUrl + "&expiry=" + Date.now();
    if (!timestamp.startsWith("http")) {
        throw new Error("Invalid URL");
    }
    const requestOptions3 = {
        Referer: doodBaseUrl
    };
    const stream = { id: "primary", type: "file", flags: [], captions: [], qualities: { unknown: { type: "mp4", url: timestamp } }, headers: requestOptions3, ...thumbnailMatch ? { thumbnailTrack: { type: "vtt", url: "https:" + thumbnailMatch[1] } } : {} };
    return {
        stream: [stream]
    };
}
async function hianimeHd1DubResolveStream(context, server, category) {
    var temporaryValue;
    const data = JSON.parse(context.url);
    const sourcesUrl = hianimeHd1DubBaseUrl + "/episode/sources?animeEpisodeId=" + data.episodeId + "&server=" + server + "&category=" + category;
    const response = await context.fetcher(sourcesUrl);
    if (response.status !== 200) {
        throw new ScraperError("No response received");
    }
    const value = response.data.sources[0];
    if (!(value != null && value.url)) {
        throw new ScraperError("No stream URL found in response");
    }
    const playlistUrl = buildProxiedHlsUrl(value.url, context.features, response.data.headers);
    const result = {
        arabic: "ar",
        english: "en",
        french: "fr",
        german: "de",
        italian: "it",
        portuguese: "pt",
        "portuguese - portugu\u00EAs (brasil)": "pt-BR",
        russian: "ru",
        spanish: "es",
        "spanish - espa\u00F1ol (la)": "es-LA",
        "spanish - espanol": "es"
    };
    const value5 = result;
    const language = ((temporaryValue = response.data.tracks) == null ? void 0 : temporaryValue.filter(item => item.lang && item.lang !== "thumbnails" && item.url).map(item => {
        const normalizedLanguage = item.lang.toLowerCase();
        const language = value5[normalizedLanguage] ??
            normalizeLanguageCode(normalizedLanguage);
        if (!language) {
            return null;
        }
        const subtitleType = getSubtitleFileType(item.url);
        if (!subtitleType) {
            return null;
        }
        return {
            id: item.url,
            url: item.url,
            language: language,
            type: subtitleType
        };
    }).filter(item => item !== null)) ?? [];
    const result2 = { ...response.data.intro.start && response.data.intro.end && { intro: { start: response.data.intro.start, end: response.data.intro.end } }, ...response.data.outro.start && response.data.outro.end && { outro: { start: response.data.outro.start, end: response.data.outro.end } } };
    const value6 = result2;
    return { stream: [{ type: "hls", id: "primary", playlist: playlistUrl, headers: response.data.headers, flags: ["cors-allowed"], captions: language, ...Object.keys(value6).length > 0 && { skips: value6 } }] };
}
function scrapeHianimeHd1Dub(context) {
    return hianimeHd1DubResolveStream(context, "hd-1", "dub");
}
function scrapeHianimeHd2Dub(context) {
    return hianimeHd1DubResolveStream(context, "hd-2", "dub");
}
function scrapeHianimeHd3Dub(context) {
    return hianimeHd1DubResolveStream(context, "hd-3", "dub");
}
function scrapeHianimeHd1Sub(context) {
    return hianimeHd1DubResolveStream(context, "hd-1", "sub");
}
function scrapeHianimeHd2Sub(context) {
    return hianimeHd1DubResolveStream(context, "hd-2", "sub");
}
function scrapeHianimeHd3Sub(context) {
    return hianimeHd1DubResolveStream(context, "hd-3", "sub");
}
const diziyouTrEmbedProvider = createEmbedProvider(diziyouTrValue);
const doodValue = cA("ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789", 10);
const doodBaseUrl = "https://d000d.com";
const doodEmbedProvider = createEmbedProvider({ id: "dood", name: "dood", rank: 173, scrape: scrapeDood });
const hianimeHd1DubBaseUrl = "https://hianime.aether.mom/api/v2/hianime";
const hianimeHd1DubEmbedProvider = createEmbedProvider({ id: "hianime-hd-1-dub", name: "HD-1 (Dub)", rank: 250, scrape: scrapeHianimeHd1Dub });
const hianimeHd2DubEmbedProvider = createEmbedProvider({ id: "hianime-hd-2-dub", name: "HD-2 (Dub)", rank: 251, scrape: scrapeHianimeHd2Dub });
const hianimeHd3DubEmbedProvider = createEmbedProvider({ id: "hianime-hd-3-dub", name: "HD-3 (Dub)", rank: 252, scrape: scrapeHianimeHd3Dub });
const hianimeHd1SubEmbedProvider = createEmbedProvider({ id: "hianime-hd-1-sub", name: "HD-1 (Sub)", rank: 253, scrape: scrapeHianimeHd1Sub });
const hianimeHd2SubEmbedProvider = createEmbedProvider({ id: "hianime-hd-2-sub", name: "HD-2 (Sub)", rank: 254, scrape: scrapeHianimeHd2Sub });
const hianimeHd3SubEmbedProvider = createEmbedProvider({ id: "hianime-hd-3-sub", name: "HD-3 (Sub)", rank: 255, scrape: scrapeHianimeHd3Sub });
const lordflixAlphaValue = "WOLVES330TIMESTAMPISFYE";
function lordflixAlphaDecryptPayload(input) {
    return CryptoJS.AES.decrypt(input, lordflixAlphaValue).toString(CryptoJS.enc.Utf8);
}
function lordflixAlphaParseHtml(input) {
    if (!input) {
        return null;
    }
    const value = input.split(" - ");
    for (const item of value) {
        ;
        {
            const language = normalizeLanguageCode(item.trim());
            if (language) {
                return language;
            }
        }
    }
    return normalizeLanguageCode(input);
}
function lordflixAlphaNormalizeLanguage(input) {
    if (!Array.isArray(input) || input.length === 0) {
        return [];
    }
    const results = [];
    for (const item of input) {
        if (!item || typeof item.file !== "string" || item.file.length === 0) {
            continue;
        }
        const subtitleType = getSubtitleFileType(item.file);
        if (!subtitleType) {
            continue;
        }
        const value = lordflixAlphaParseHtml(item.language);
        if (!value) {
            continue;
        }
        const stream = {
            id: item.file,
            url: item.file,
            language: value,
            type: subtitleType,
            hasCorsRestrictions: false
        };
        results.push(stream);
    }
    return deduplicateCaptionsByLanguage(results);
}
async function scrapeLordflixAlpha(context) {
    if (!context.url) {
        throw new ScraperError("Alpha URL missing");
    }
    const result = {
        Accept: "application/json"
    };
    const requestOptions = {
        headers: result
    };
    const response = await context.proxiedFetcher(context.url, requestOptions);
    if (!(response != null && response.data)) {
        throw new ScraperError("Alpha response missing data");
    }
    const value = lordflixAlphaDecryptPayload(response.data);
    if (!value) {
        throw new ScraperError("Alpha decryption failed");
    }
    let temporaryValue;
    try {
        temporaryValue = JSON.parse(value);
    }
    catch {
        throw new ScraperError("Alpha invalid JSON");
    }
    if (!temporaryValue.source) {
        throw new ScraperError("Alpha source not found");
    }
    const value3 = lordflixAlphaNormalizeLanguage(temporaryValue.subtitles);
    const playlistUrl = buildProxiedHlsUrl(temporaryValue.source, context.features, { Referer: "https://videostr.net/", Origin: "https://videostr.net" });
    const requestOptions2 = {
        Referer: "https://videostr.net/",
        Origin: "https://videostr.net"
    };
    const stream = {
        id: "primary",
        type: "hls",
        playlist: playlistUrl,
        flags: ["cors-allowed"],
        captions: value3,
        headers: requestOptions2
    };
    return {
        stream: [stream]
    };
}
async function scrapeLordflixKanye(context) {
    if (!context.url) {
        throw new ScraperError("Kanye URL missing");
    }
    const result = {
        Accept: "application/json"
    };
    const requestOptions = {
        headers: result
    };
    const response = await context.proxiedFetcher(context.url, requestOptions);
    if (!(response != null && response.data)) {
        throw new ScraperError("Kanye obf data missing");
    }
    const value = lordflixAlphaDecryptPayload(response.data);
    if (!value) {
        throw new ScraperError("Kanye decryption failed");
    }
    let temporaryValue;
    try {
        temporaryValue = JSON.parse(value);
    }
    catch {
        throw new ScraperError("Kanye invalid JSON");
    }
    if (!temporaryValue.data) {
        throw new ScraperError("Kanye data not found");
    }
    const requestUrl = "https://whyiloveyou.lordflix.club/4K/" + temporaryValue.data + ".m3u8";
    const playlistUrl = buildProxiedHlsUrl(requestUrl, context.features, { Referer: "https://vidsync.xyz/", Origin: "https://vidsync.xyz" });
    const stream = {
        id: "primary",
        type: "hls",
        playlist: playlistUrl,
        flags: ["cors-allowed"],
        captions: [],
        headers: {}
    };
    stream.headers.Referer = "https://vidsync.xyz/";
    stream.headers.Origin = "https://vidsync.xyz";
    return {
        stream: [stream]
    };
}
const lordflixAlphaProviderConfig = {
    id: "lordflix-alpha",
    name: "Alpha",
    rank: 1180,
    scrape: scrapeLordflixAlpha
};
const lordflixAlphaProvider = createEmbedProvider(lordflixAlphaProviderConfig);
const lordflixKanyeProviderConfig = {
    id: "lordflix-kanye",
    name: "Kanye (4K)",
    rank: 1181,
    disabled: true,
    scrape: scrapeLordflixKanye
};
async function scrapeMixdrop(context) {
    let url = context.url;
    if (context.url.includes("primewire")) {
        (url = (await context.fetcher.full(context.url)).finalUrl);
    }
    const parsedUrl = new URL(url).pathname.split("/")[2];
    const result = {
        baseUrl: mixdropBaseUrl
    };
    const response = await context.proxiedFetcher("/e/" + parsedUrl, result);
    const match = response.match(mixdropPatterns);
    if (!match) {
        throw new Error("failed to find packed mixdrop JavaScript");
    }
    const value = Ch.unpack(match[1]);
    const match5 = value.match(mixdropPatterns2);
    if (!match5) {
        throw new Error("failed to find packed mixdrop source link");
    }
    const value3 = match5[1];
    const requestOptions = {
        Referer: mixdropBaseUrl
    };
    return { stream: [{ id: "primary", type: "file", flags: ["ip-locked"], captions: [], qualities: { unknown: { type: "mp4", url: value3.startsWith("http") ? value3 : "https:" + value3, headers: requestOptions } } }] };
}
const lordflixKanyeProvider = createEmbedProvider(lordflixKanyeProviderConfig);
const mixdropBaseUrl = "https://mixdrop.ag";
const mixdropPatterns = /(eval\(function\(p,a,c,k,e,d\){.*{}\)\))/;
const mixdropPatterns2 = /MDCore\.wurl="(.*?)";/;
const mixdropEmbedProvider = createEmbedProvider({ id: "mixdrop", name: "MixDrop", rank: 198, scrape: scrapeMixdrop });
const upcloudBaseUrl = "https://videostr.net";
const upcloudPatterns = [/<div data-dpi="([^"]+)" style="display:none">/, /<meta name="_gg_fb" content="([^"]+)">/, /<!-- _is_th:([^ ]+) -->/, /window\._xy_ws = "([^"]+)"/, /nonce="([^"]+)"/, /window\._lk_db = {x: "([^"]+)", y: "([^"]+)", z: "([^"]+)"}/];
function upcloudExtractValue(text) {
    for (const item of upcloudPatterns) {
        const match = text.match(item);
        if (match) {
            return match.length
                ===
                    4
                ? "" + match[1] + match[2] + match[3] : match[1];
        }
    }
    return null;
}
async function scrapeUpcloud(context) {
    const response = await context.proxiedFetcher(context.url, { headers: { Referer: context.url } });
    const document = loadHtml(response);
    const dataId = document("#megacloud-player").attr("data-id");
    if (!dataId) {
        throw new ScraperError("Could not find data-id");
    }
    const extractedKey = upcloudExtractValue(response);
    if (!extractedKey) {
        throw new ScraperError("Could not find k-value");
    }
    const sourcesUrl = upcloudBaseUrl + "/embed-1/v3/e-1/getSources?id=" + dataId + "&_k=" + extractedKey;
    const sourcesResponse = await context.proxiedFetcher(sourcesUrl, { headers: { "X-Requested-With": "XMLHttpRequest", Referer: context.url } });
    if (!sourcesResponse.sources) {
        throw new ScraperError("No sources found");
    }
    const captions = [];
    if (sourcesResponse.tracks) {
        for (const track of sourcesResponse.tracks) {
            const language = normalizeLanguageCode(track.label);
            const subtitleType = getSubtitleFileType(track.file);
            if (!language
                ||
                    !subtitleType) {
                continue;
            }
            const caption = {
                id: track.file,
                url: track.file,
                language: language,
                type: subtitleType,
                hasCorsRestrictions: false
            };
            captions.push(caption);
        }
    }
    const requestOptions = {
        Referer: "https://videosrt.net/"
    };
    const value = requestOptions;
    const playlistUrl = buildProxiedHlsUrl(sourcesResponse.sources[0].file, context.features, value);
    const stream = {
        id: "primary",
        playlist: playlistUrl,
        type: "hls",
        flags: ["cors-allowed"],
        captions: captions,
        headers: value
    };
    return {
        stream: [stream]
    };
}
async function scrapeVidmoly(context) {
    const response = await context.proxiedFetcher(context.url);
    const sourcesUrl = response.match(/sources:\s*\[{file:"([^"]+.m3u8)"}\]/)?.[1];
    if (!sourcesUrl) {
        throw new ScraperError("No stream found");
    }
    return { stream: [{ id: "primary", type: "hls", playlist: buildProxiedHlsUrl(sourcesUrl, context.features, { Referer: "https://vidmoly.to/" }), headers: { Referer: "https://vidmoly.to/" }, flags: ["cors-allowed"], captions: [] }] };
}
const upcloudEmbedProvider = createEmbedProvider({ id: "upcloud", name: "UpCloud", rank: 201, scrape: scrapeUpcloud });
const vidmolyEmbedProvider = createEmbedProvider({ id: "vidmoly", name: "Vidmoly", rank: 40, scrape: scrapeVidmoly });
const autoembedBaseUrl = "https://autoembed.pro";
async function decodeBase64(encoded) {
    const alphabet = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/=";
    const input = encoded.replace(/=+$/, "");
    let output = "";
    if (input.length % 4 === 1) {
        throw new Error("The string to be decoded is not correctly encoded.");
    }
    for (let blockIndex = 0, buffer = 0, index = 0; index < input.length; index++) {
        const character = input.charAt(index);
        const value = alphabet.indexOf(character);
        if (value === -1) {
            continue;
        }
        buffer = blockIndex % 4 ? buffer * 64 + value : value;
        if (blockIndex++ % 4) {
            output += String.fromCharCode(255 & (buffer >> ((-2 * blockIndex) & 6)));
        }
    }
    return output;
}
async function scrapeAutoembed(context) {
    const mediaType = context.media.type === "show" ? "tv" : "movie";
    let embedUrl = `${autoembedBaseUrl}/embed/${mediaType}/${context.media.tmdbId}`;
    if (context.media.type === "show") {
        embedUrl += `/${context.media.season.number}/${context.media.episode.number}`;
    }
    const response = await context.proxiedFetcher(embedUrl, {
        headers: { Referer: autoembedBaseUrl }
    });
    if (!response) {
        throw new ScraperError("Failed to fetch video source");
    }
    const document = loadHtml(response);
    let iframeUrl = document("iframe").attr("src");
    if (!iframeUrl) {
        const configText = document("#Vconfig").html();
        if (configText) {
            try {
                const config = JSON.parse(configText);
                if (config.url) {
                    iframeUrl = config.url;
                }
            }
            catch {
                try {
                    const decodedConfig = JSON.parse(await decodeBase64(configText));
                    if (decodedConfig.url) {
                        iframeUrl = decodedConfig.url;
                    }
                }
                catch {
                }
            }
        }
        else {
            const match = response.match(/window\.vConfig\s*=\s*JSON\.parse\(atob\(`([^`]+)/i);
            const encodedConfig = match?.[1];
            if (encodedConfig) {
                const decodedConfig = JSON.parse(await decodeBase64(encodedConfig));
                if (decodedConfig?.url) {
                    iframeUrl = decodedConfig.url;
                }
            }
        }
    }
    if (!iframeUrl) {
        throw new ScraperError("Failed to find iframe src");
    }
    context.progress(50);
    const embeds = [{
            embedId: "autoembed-english",
            url: iframeUrl
        }];
    context.progress(90);
    return { embeds };
}
const autoembedProviderConfig = {
    id: "autoembed",
    name: "Autoembed \uD83D\uDD2E",
    rank: 550,
    disabled: true,
    flags: ["cors-allowed"],
    scrapeMovie: scrapeAutoembed,
    scrapeShow: scrapeAutoembed
};
const autoembedProvider = createSourceProvider(autoembedProviderConfig);
const autoembedBaseUrl2 = "https://cinevibe.asia";
const autoembedValue = "Mozilla/5.0 (Linux; Android 10; K) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Mobile Safari/537.36";
const autoembedValue2 = "eyJzY3JlZW4iOiIzNjB4ODA2eDI0Iiwi";
const autoembedValue3 = "pjght152dw2rb.ssst4bzleDI0Iiwibv78";
function autoembedParseHtml(input) {
    let value = 2166136261;
    for (const item of input)
        value ^= item.charCodeAt(0), value = value + (value <<
            1) + (value <<
            4)
            +
                (value <<
                    7) +
            (value <<
                8)
            +
                (value << 24)
            >>> 0;
    return (value >>>
        0).toString(16).padStart(8, "0");
}
function cinevibeDecodePayload(input) {
    let value = btoa(input);
    value = value.split("").reverse().join("");
    value = value.replace(/[a-zA-Z]/g, argument1 => {
        const characterCode = argument1 <= "Z" ? 65 : 97;
        return String.fromCharCode((argument1.charCodeAt(0) - characterCode + 13) % 26 + characterCode);
    });
    value = btoa(value);
    return value.replace(/\+/g, "-").replace(/\//g, "_").replace(/=/g, "");
}
async function scrapeCinevibe(context) {
    var temporaryValue;
    const value = context.media.tmdbId.toString();
    const type2 = context.media.type;
    const title2 = context.media.title;
    const url = context.media.releaseYear.toString();
    if (type2 === "show") {
        throw new ScraperError("TV Series currently not supported");
    }
    const timestamp = Math.floor(Date.now()
        /
            300000) + "_" + autoembedValue2 + "_cinevibe_2025";
    const normalizedValue = title2.toLowerCase().replace(/[^a-z0-9]/g, "");
    const timestamp4 = autoembedValue3 + "|" + value + "|" + normalizedValue + "|" + url + "||" +
        autoembedParseHtml(timestamp) + "|" + Math.floor(Date.now()
        /
            600000) + "|" + autoembedValue2;
    const url3 = cinevibeDecodePayload(timestamp4);
    const timestamp5 = autoembedBaseUrl2 + "/api/stream/fetch?server=cinebox-1&type=" + type2 + "&mediaId=" + value + "&title=" + encodeURIComponent(title2) + "&releaseYear=" + url + "&_token=" + url3 + "&_ts=" + Date.now();
    context.progress(50);
    const requestOptions = {
        Referer: autoembedBaseUrl2,
        "User-Agent": autoembedValue,
        "X-CV-Fingerprint": autoembedValue2,
        "X-CV-Session": autoembedValue3,
        "X-Requested-With": "XMLHttpRequest"
    };
    const value9 = requestOptions;
    let temporaryValue4;
    try {
        const parts = "4|1|2|3|0".split("|");
        let value10 = 0;
        for (;;) {
            switch (parts[value10++]) {
                case "0":
                    context.progress(90);
                    continue;
                case "1":
                    if (!temporaryValue4 || typeof temporaryValue4 !== "object") {
                        throw console.error("Invalid response format from cinevibe API:", typeof temporaryValue4, (temporaryValue4?.length) || "unknown size"), new ScraperError("Invalid response format from streaming API");
                    }
                    continue;
                case "2":
                    if (!temporaryValue4.sources && !temporaryValue4.streams) {
                        throw console.error("Response missing expected fields:", Object.keys(temporaryValue4)), new ScraperError("Response missing expected streaming data");
                    }
                    continue;
                case "3":
                    if (!temporaryValue4.sources || !Array.isArray(temporaryValue4.sources) ||
                        temporaryValue4.sources.length
                            ===
                                0) {
                        throw new ScraperError("No stream sources found");
                    }
                    continue;
                case "4":
                    const requestOptions2 = { ...value9 };
                    requestOptions2["User-Agent"] = value9["User-Agent"];
                    const requestOptions3 = {};
                    requestOptions3.headers = requestOptions2, temporaryValue4 = await context.proxiedFetcher(timestamp5, requestOptions3);
                    continue;
            }
            break;
        }
    }
    catch (temporaryValue5) {
        throw temporaryValue5 instanceof
            Error
            && temporaryValue5.message.includes("string longer than") ? (console.error("cinevibe API returned oversized response (likely video file instead of JSON)"), new ScraperError("API returned invalid response format - likely direct video stream")) : temporaryValue5;
    }
    const result = {};
    for (const streamItem of temporaryValue4.sources) {
        if (streamItem.url &&
            streamItem.streamType
                === "mp4") {
            const normalizedValue2 = ((temporaryValue = streamItem.server) == null ? void 0 : temporaryValue.toLowerCase()) || "";
            if (normalizedValue2.includes("1080")) {
                result["1080"] = { type: "mp4", url: streamItem.url };
            }
            else if (normalizedValue2.includes("720")) {
                result["720"] = { type: "mp4", url: streamItem.url };
            }
            else if (normalizedValue2.includes("480")) {
                const stream = {
                    type: "mp4",
                    url: streamItem.url
                };
                result["480"] = stream;
            }
            else if (normalizedValue2.includes("360")) {
                const stream3 = {
                    type: "mp4",
                    url: streamItem.url
                };
                result["360"] = stream3;
            }
            else {
                const stream4 = {
                    type: "mp4",
                    url: streamItem.url
                };
                result.unknown = stream4;
            }
        }
    }
    const items = temporaryValue4.subtitles ? temporaryValue4.subtitles.filter(item => item.file && item.label).map(item => ({ id: item.key || item.label, url: item.file, type: item.type === "srt" ? "srt" : "vtt", hasCorsRestrictions: false, language: item.label.toLowerCase().includes("english") ? "en" : "unknown" })) : [];
    const requestOptions4 = {
        Referer: autoembedBaseUrl2 + "/",
        Origin: autoembedBaseUrl2
    };
    const requestOptions5 = {
        id: "primary",
        type: "file",
        qualities: result,
        headers: requestOptions4,
        flags: [],
        captions: items
    };
    return {
        embeds: [],
        stream: [requestOptions5]
    };
}
const cinevibeProviderConfig = {
    id: "cinevibe",
    name: "Vibe \uD83C\uDF00",
    rank: 223,
    disabled: true,
    flags: [],
    scrapeMovie: scrapeCinevibe,
    scrapeShow: scrapeCinevibe
};
const cinevibeProvider = createSourceProvider(cinevibeProviderConfig);
const diziyouBaseUrl = "https://www.diziyou.to";
async function scrapeDiziyouShow(context) {
    const response = await context.proxiedFetcher("/wp-admin/admin-ajax.php", { baseUrl: diziyouBaseUrl, method: "POST", body: new URLSearchParams({ action: "data_fetch", keyword: context.media.title }).toString(), headers: { "Content-Type": "application/x-www-form-urlencoded" } });
    const document = loadHtml(response);
    let temporaryValue;
    if (document("div#searchelement").each((index, element) => {
        const value = document(element), match = value.find("#search-cat-year").text().trim(), match4 = value.find("a").last().text().trim(), url = value.find("a").attr("href");
        if (url && match4.toLowerCase() === context.media.title.toLowerCase() && match === context.media.releaseYear.toString())
            return temporaryValue = url, false;
    }), !temporaryValue) {
        throw new ScraperError("Media not found");
    }
    const response2 = await context.proxiedFetcher(temporaryValue);
    const document4 = loadHtml(response2);
    let temporaryValue3;
    if (document4("div.container a").each((index3, element3) => {
        const value4 = document4(element3), url = value4.attr("href"), value5 = value4.text();
        if (url && value5.includes(context.media.season.number + ". Sezon " + context.media.episode.number + ". B\u00F6l\u00FCm")) {
            return temporaryValue3 = url, false;
        }
    }), !temporaryValue3) {
        throw new ScraperError("Episode not found");
    }
    const response3 = await context.proxiedFetcher(temporaryValue3);
    const document5 = loadHtml(response3);
    const value = document5("iframe#diziyouPlayer").attr("src");
    if (!value) {
        throw new ScraperError("Player not found");
    }
    const match = value.match(/\/player\/(\d+)\.html/);
    if (!match) {
        throw new ScraperError("Episode ID not found");
    }
    const url = match[1];
    const embed = {
        embedId: "diziyou-en",
        url: url
    };
    const embed3 = {
        embedId: "diziyou-tr",
        url: url
    };
    return {
        embeds: [embed, embed3]
    };
}
const diziyouProviderConfig = {
    id: "diziyou",
    name: "Kl (Turkish) \uD83C\uDF6D",
    rank: 830,
    flags: ["cors-allowed"],
    scrapeShow: scrapeDiziyouShow
};
const diziyouProvider = createSourceProvider(diziyouProviderConfig);
const ee3BaseUrl = "https://borg.rips.cc";
const ee3Value = "ddd00wow";
const ee3Value2 = "+rS:ewe52Pj!p~F";
async function ee3ResolveStream(context, key2) {
    const result = {
        identity: ee3Value,
        password: key2
    };
    const response = await context.proxiedFetcher.full(ee3BaseUrl + "/api/collections/users/auth-with-password?expand=lists_liked", { method: "POST", headers: { Origin: "https://ee3.me", "Content-Type": "application/json" }, body: JSON.stringify(result) });
    if (response.statusCode !== 200) {
        throw new Error("Auth failed with status: " + response.statusCode + ": " + JSON.stringify(response.body));
    }
    const body2 = response.body;
    if (!(body2 != null && body2.token)) {
        throw new Error("No token in auth response: " + JSON.stringify(body2));
    }
    const token2 = body2.token;
    context.progress(20);
    const requestUrl = ee3BaseUrl + "/api/collections/movies/records?page=1&perPage=48&filter=tmdb_data.id%20~%20" + context.media.tmdbId;
    const requestOptions = {
        Authorization: "Bearer " + token2,
        Origin: "https://ee3.me"
    };
    const requestOptions2 = {
        headers: requestOptions
    };
    const url = await context.proxiedFetcher.full(requestUrl, requestOptions2);
    if (url.statusCode
        !==
            200) {
        throw new Error("Movie lookup failed with status: " + url.statusCode + ": " + JSON.stringify(url.body));
    }
    const body3 = url.body;
    if (!(body3 != null && body3.items) ||
        body3.items.length
            ===
                0) {
        throw new ScraperError("No items found for TMDB ID " + context.media.tmdbId + ": " + JSON.stringify(body3));
    }
    if (!body3.items[0].video) {
        throw new ScraperError("No video field in first item: " + JSON.stringify(body3.items[0]));
    }
    const video2 = body3.items[0].video;
    context.progress(40);
    const requestOptions3 = {
        Authorization: "Bearer " + token2,
        Origin: "https://ee3.me"
    };
    const requestOptions4 = {
        headers: requestOptions3
    };
    const url2 = await context.proxiedFetcher.full(ee3BaseUrl + "/video/" + video2 + "/key", requestOptions4);
    if (url2.statusCode
        !==
            200) {
        throw new Error("Key fetch failed with status: " + url2.statusCode + ": " + JSON.stringify(url2.body));
    }
    const body4 = url2.body;
    if (!(body4 != null && body4.key)) {
        throw new Error("No key in response: " + JSON.stringify(body4));
    }
    context.progress(60);
    return video2 + "?k=" + body4.key;
}
async function scrapeEe3Movie(context) {
    const value = await ee3ResolveStream(context, ee3Value2);
    if (!value) {
        throw new ScraperError("No watchable item found");
    }
    context.progress(80);
    const url = ee3BaseUrl + "/video/" + value;
    const requestOptions = {
        id: "primary",
        type: "file",
        qualities: {},
        headers: {},
        flags: [],
        captions: []
    };
    requestOptions.qualities.unknown = {};
    requestOptions.qualities.unknown.type = "mp4";
    requestOptions.qualities.unknown.url = url;
    requestOptions.headers.Origin = "https://ee3.me";
    return {
        embeds: [],
        stream: [requestOptions]
    };
}
const ee3ProviderConfig = {
    id: "ee3",
    name: "EE3",
    rank: 176,
    disabled: true,
    flags: [],
    scrapeMovie: scrapeEe3Movie
};
const ee3Provider = createSourceProvider(ee3ProviderConfig);
function fsharetvGetFileExtension(input) {
    let value = input.trim().toLowerCase();
    value !== "the movie" && value.endsWith("the movie") && (value = value.replace("the movie", ""));
    value !== "the series" && value.endsWith("the series") && (value = value.replace("the series", ""));
    return value.replace(/['":]/g, "").replace(/[^a-zA-Z0-9]+/g, "_");
}
function fsharetvProcessData(input, argument2) {
    return fsharetvGetFileExtension(input) === fsharetvGetFileExtension(argument2);
}
function fsharetvProcessData2(input, argument2, argument3) {
    const value = argument3 === void 0 ? true : input.releaseYear === argument3;
    return fsharetvProcessData(input.title, argument2) && value;
}
function fsharetvMapQuality(input) {
    switch (input.toLowerCase().replace("p", "")) {
        case "360": return "360";
        case "480": return "480";
        case "720": return "720";
        case "1080": return "1080";
        case "2160": return "4k";
        case "4k": return "4k";
        default: return "unknown";
    }
}
const fsharetvBaseUrl = "https://fsharetv.co";
async function scrapeFsharetvMovie(context) {
    const response = await context.proxiedFetcher("/search", { baseUrl: fsharetvBaseUrl, query: { q: context.media.title } });
    const document = loadHtml(response);
    const captions = [];
    document(".movie-item").each((index, element) => {
        var value;
        const [, itemValue, itemValue2] = ((value = document(element).find("b").text()) == null ? void 0 : value.match(/^(.*?)\s*(?:\(?\s*(\d{4})(?:\s*-\s*\d{0,4})?\s*\)?)?\s*$/)) || [];
        const url = document(element).find("a").attr("href");
        !itemValue || !url || captions.push({ title: itemValue, year: Number(itemValue2) ?? void 0, url: url });
    });
    const item = captions.find(item => item && fsharetvProcessData2(context.media, item.title, item.year))?.url;
    if (!item) {
        throw new ScraperError("No watchable item found");
    }
    context.progress(50);
    const result = {
        baseUrl: fsharetvBaseUrl
    };
    const response2 = await context.proxiedFetcher(item.replace("/movie", "/w"), result);
    const match = response2.match(/Movie\.setSource\('([^']*)'/)?.[1];
    if (!match) {
        throw new Error("File ID not found");
    }
    const stream = {
        type: "watch"
    };
    const requestOptions3 = {
        baseUrl: fsharetvBaseUrl,
        query: stream
    };
    const sourceResponse = await context.proxiedFetcher("/api/file/" + match + "/source", requestOptions3);
    if (!sourceResponse.data.file.sources.length) {
        throw new Error("No sources found");
    }
    const requestOptions4 = {
        baseUrl: fsharetvBaseUrl
    };
    const parsedUrl = new URL((await context.proxiedFetcher.full(sourceResponse.data.file.sources[0].src, requestOptions4)).finalUrl).origin;
    const value = sourceResponse.data.file.sources.reduce((accumulator, item) => {
        const type2 = typeof item.quality == "number" ? item.quality.toString() : item.quality;
        const value = fsharetvMapQuality(type2);
        accumulator[value] = { type: "mp4", url: "" + parsedUrl + item.src.replace("/api", "") };
        return accumulator;
    }, {});
    context.progress(90);
    const requestOptions = {
        referer: "https://fsharetv.co"
    };
    const requestOptions2 = {
        id: "primary",
        type: "file",
        flags: [],
        headers: requestOptions,
        qualities: value,
        captions: []
    };
    return {
        embeds: [],
        stream: [requestOptions2]
    };
}
const fsharetvProviderConfig = {
    id: "fsharetv",
    name: "Fshare \uD83D\uDC7D",
    rank: 170,
    flags: [],
    scrapeMovie: scrapeFsharetvMovie
};
const fsharetvProvider = createSourceProvider(fsharetvProviderConfig);
const fsharetvCache = new Map;
function fsharetvProcessData3(input) {
    return input.toLowerCase().replace(/[^a-z0-9]+/g, " ").trim();
}
function fsharetvProcessData4(input, argument2) {
    return input === "show" ? ["TV", "TV_SHORT", "OVA", "ONA", "SPECIAL"].includes(argument2.format) : argument2.format === "MOVIE";
}
const fsharetvValue = "\nquery ($search: String, $type: MediaType) {\n  Page(page: 1, perPage: 20) {\n    media(search: $search, type: $type, sort: POPULARITY_DESC) {\n      id\n      type\n      format\n      seasonYear\n      title {\n        romaji\n        english\n        native\n      }\n    }\n  }\n}\n";
async function fsharetvLookupEpisode(context, argument2) {
    const value = argument2.type + ":" + argument2.title + ":" + argument2.releaseYear;
    const value7 = fsharetvCache.get(value);
    if (value7) {
        return value7;
    }
    const response = await context.proxiedFetcher("", { baseUrl: "https://graphql.anilist.co", method: "POST", headers: { "Content-Type": "application/json", Accept: "application/json" }, body: JSON.stringify({ query: fsharetvValue, variables: { search: argument2.title, type: "ANIME" } }) });
    const value8 = (response.data?.Page?.media) ?? [];
    if (!value8.length) {
        throw new Error("AniList id not found");
    }
    const value9 = fsharetvProcessData3(argument2.title);
    const items = value8.filter(item => fsharetvProcessData4(argument2.type, item)).map(item => {
        const items2 = [item.title.romaji];
        item.title.english && items2.push(item.title.english);
        item.title.native && items2.push(item.title.native);
        const filteredItems = items2.map(fsharetvProcessData3).filter(Boolean);
        const value = filteredItems.includes(value9);
        const value11 = filteredItems.some(item => item.includes(value9) || value9.includes(item));
        const value12 = item.seasonYear ? Math.abs(item.seasonYear
            -
                argument2.releaseYear) : 5;
        let value13 = 0;
        value ? value13 += 100 : value11 && (value13 += 50);
        value13 += Math.max(0, 20
            - value12 *
                4);
        return {
            it: item,
            score: value13
        };
    }).sort((left, right) => right.score - left.score);
    const value10 = items[0];
    // Require a strong title match — never fall back to AniList's first popular hit
    // (that turned "House of the Dragon" into a random anime).
    if (!value10 || value10.score < 70) {
        throw new Error("AniList id not found");
    }
    const value11 = value10.it?.id;
    if (!value11) {
        throw new Error("AniList id not found");
    }
    fsharetvCache.set(value, value11);
    return value11;
}
const hianimeValue = "\nquery ($id: Int) {\n  Media(id: $id, type: ANIME) {\n    title {\n      romaji\n      english\n      native\n    }\n    synonyms\n  }\n}\n";
async function hianimeFetchData(context, argument2) {
    try {
        ;
        {
            const value = await fsharetvLookupEpisode(context, argument2);
            const result = {
                id: value
            };
            const result2 = {
                query: hianimeValue,
                variables: result
            };
            const response = await context.proxiedFetcher("", { baseUrl: "https://graphql.anilist.co", method: "POST", headers: { "Content-Type": "application/json", Accept: "application/json" }, body: JSON.stringify(result2) });
            const english2 = response.data.Media.title.english;
            return english2 ? english2.toLowerCase() : null;
        }
    }
    catch {
        return null;
    }
}
const hianimeValue2 = "limon87";
const hianimeBaseUrl = "https://gem.aether.mom/v1beta/models/gemini-2.5-flash-lite:generateContent";
function hianimeProcessData(media, key, key2) {
    const value = media.season.number > 1 ? " and has " + media.season.number + " seasons" : "";
    const value3 = key2 ? " (AniList English title: \"" + key2 + '")' : "";
    return ("\n    You are an AI that matches TMDB movie and show data to hianime search results.\n    The user is searching for \"" + media.title + '"' + value3 + " which was released in " + media.releaseYear + value + ".\n    The user is looking for season " + media.season.number + " (TMDB title: \"" + media.season.title + "\", " + (media.season.episodeCount ?? "unknown") + " episodes), episode " + media.episode.number + ".\n\n    Here are the search results from hianime:\n    " + JSON.stringify(key, null, 2) + "\n\n    IMPORTANT: Some shows on TMDB have continuous episode numbering across seasons (e.g., episode 25 is the first episode of season 2), but hianime lists seasons as separate entries with their own episode counts. The hianime entry may also have a different title (e.g., \"Mugen Train Arc\").\n    To solve this, please return a JSON object with a \"results\" array that contains ALL entries from the search results that match the requested show, including all of its seasons, even if the user is only asking for one.\n    Each object in the \"results\" array should have the \"id\" of the matching anime from the hianime search results, and the \"season\" number. You must determine the season number for each entry based on its title.\n    The results MUST be sorted by season number in ascending order so the calling code can correctly map the episode number.\n    Pay close attention to the season title and episode counts from both TMDB and the hianime results to find the best match. If TMDB combines seasons into one, you must split them based on the episode counts in the search results.\n    Use the TMDB season title as the primary key for matching, and do not assign the same season number to different arcs.\n    Your response must only be the raw JSON object, without any markdown formatting, comments, or other text.\n  ").trim();
}
async function hianimeFetchData2(context, key, key2, key3) {
    try {
        const value = hianimeProcessData(key, key2, key3);
        const result = {
            "Content-Type": "application/json",
            "x-goog-api-key": hianimeValue2
        };
        const result2 = {
            text: value
        };
        const result3 = {
            parts: [result2]
        };
        const result4 = {
            contents: [result3]
        };
        const response = await context.fetcher(hianimeBaseUrl, { method: "POST", headers: result, body: JSON.stringify(result4) });
        const text2 = response.candidates[0].content.parts[0].text;
        const value5 = text2.indexOf("{");
        const value6 = text2.lastIndexOf("}");
        if (value5 === -1 ||
            value6 ===
                -1) {
            throw new Error("Invalid AI response: No JSON object found");
        }
        const value7 = text2.substring(value5, value6 +
            1);
        const data = JSON.parse(value7);
        if (!data.results || !Array.isArray(data.results)) {
            throw new Error("Invalid AI response format");
        }
        return data;
    }
    catch (temporaryValue) {
        if (temporaryValue instanceof
            Error) {
            context.progress(0);
        }
        return null;
    }
}
async function scrapeHianimeShow(context) {
    var temporaryValue;
    var temporaryValue6;
    var temporaryValue7;
    const value = await hianimeFetchData(context, context.media);
    const results5 = [];
    const url = value ? [context.media.title, value] : [context.media.title];
    for (const item of url)
        try {
            const response = await context.fetcher(hianimeBaseUrl2 + "/search?q=" +
                encodeURIComponent(item) + "&page=1");
            if ((temporaryValue = response?.data) != null && temporaryValue.animes) {
                results5.push(...response.data.animes);
            }
        }
        catch {
        }
    const results6 = [...new Map(results5.map(item => [item.id, item])).values()];
    if (results6.length
        ===
            0) {
        throw new ScraperError("Anime not found");
    }
    const filteredItems = results6.filter(item => item.type === "TV");
    const value7 = await hianimeFetchData2(context, context.media, filteredItems, value);
    let results7 = [];
    if (value7 && value7.results.length > 0) {
        results7 = value7.results.map(item => {
            const match = filteredItems.find(anime => anime.id === item.id);
            if (!match)
                return null;
            const result = { ...match };
            return result.seasonNum = item.season ?? 1, result;
        }).filter(item => item !== null).sort((left, right) => left.seasonNum - right.seasonNum);
    }
    // Gemini match often fails in lab — fall back to best title match.
    if (!results7.length) {
        const want = fsharetvProcessData3(context.media.title || "");
        const scored = filteredItems.map((anime) => {
            const names = [anime.name, anime.jname].filter(Boolean).map(fsharetvProcessData3);
            let score = 0;
            for (const n of names) {
                if (!n || !want) continue;
                if (n === want) score = Math.max(score, 100);
                else if (n.includes(want) || want.includes(n)) score = Math.max(score, 80);
            }
            return { anime, score };
        }).filter((x) => x.score > 0).sort((a, b) => b.score - a.score);
        if (!scored.length) {
            throw new ScraperError("Anime not found");
        }
        results7 = [{ ...scored[0].anime, seasonNum: context.media.season.number || 1 }];
    }
    let temporaryValue8;
    let match = results7.find(item => item.seasonNum === context.media.season.number);
    const filteredItems2 = results7.filter(item => item.seasonNum === context.media.season.number);
    if (filteredItems2.length
        >
            1
        && (match = filteredItems2.sort((left3, right3) => {
            const value = left3.name, value9 = right3.name, title2 = context.media.season.title;
            return Number(fsharetvProcessData(value9, title2)) -
                Number(fsharetvProcessData(value, title2));
        })[0]), match) {
        const response2 = await context.fetcher(hianimeBaseUrl2 + "/anime/" + match.id + "/episodes");
        if ((temporaryValue6 = response2?.data) != null && temporaryValue6.episodes) {
            const match2 = response2.data.episodes.find(item => item.number === context.media.episode.number);
            if (match2) {
                (temporaryValue8 = match2.episodeId);
            }
        }
    }
    if (!temporaryValue8) {
        let number2 = context.media.episode.number;
        for (const temporaryValue9 of results7) {
            const value8 = temporaryValue9.episodes.sub ?? 0;
            if (number2 <= value8) {
                const value9 = number2;
                const response3 = await context.fetcher(hianimeBaseUrl2 + "/anime/" + temporaryValue9.id + "/episodes");
                if ((temporaryValue7 = response3?.data) != null && temporaryValue7.episodes) {
                    const match3 = response3.data.episodes.find(item => item.number === value9);
                    if (match3) {
                        temporaryValue8 = match3.episodeId;
                        break;
                    }
                }
            }
            if (temporaryValue8) {
                break;
            }
            number2 -= value8;
        }
    }
    if (!temporaryValue8) {
        throw new ScraperError("Episode not found");
    }
    const result = {
        episodeId: temporaryValue8
    };
    const result2 = {
        episodeId: temporaryValue8
    };
    const url3 = ["hd-1", "hd-2", "hd-3"].flatMap(argument1 => [{ embedId: "hianime-" + argument1 + "-dub", url: JSON.stringify(result) }, { embedId: "hianime-" + argument1 + "-sub", url: JSON.stringify(result2) }]);
    return {
        embeds: url3
    };
}
const hianimeBaseUrl2 = "https://hianime.aether.mom/api/v2/hianime";
const hianimeProviderConfig = {
    id: "hianime",
    name: "HiAnime \u26E9\uFE0F",
    rank: 820,
    disabled: false,
    flags: ["cors-allowed"],
    scrapeShow: scrapeHianimeShow
};
const hianimeProvider = createSourceProvider(hianimeProviderConfig);
const insertunitBaseUrl = "https://isut.streamflix.one";
async function scrapeInsertunit(context) {
    const response = await context.fetcher(insertunitBaseUrl + "/api/source/" + (context.media.type === "movie" ? "" + context.media.tmdbId : context.media.tmdbId + "/" + context.media.season.number + "/" + context.media.episode.number));
    const sources2 = response.sources;
    if (!sources2 || sources2.length === 0) {
        throw new ScraperError("No sources found");
    }
    const file2 = sources2[0].file;
    if (!file2) {
        throw new ScraperError("No file URL found");
    }
    context.progress(90);
    const stream = {
        id: "primary",
        playlist: file2,
        type: "hls",
        flags: ["cors-allowed"],
        captions: []
    };
    return {
        embeds: [],
        stream: [stream]
    };
}
const insertunitProviderConfig = {
    id: "insertunit",
    name: "Insertunit \uD83C\uDF0D",
    rank: 12,
    disabled: true,
    flags: ["cors-allowed", "ip-locked"],
    scrapeMovie: scrapeInsertunit,
    scrapeShow: scrapeInsertunit
};
const insertunitProvider = createSourceProvider(insertunitProviderConfig);
const mp4hydraBaseUrl = "https://mp4hydra.org/";
async function scrapeMp4hydra(context) {
    const response = await context.proxiedFetcher("/search", { baseUrl: mp4hydraBaseUrl, query: { q: context.media.title } });
    context.progress(40);
    const document = loadHtml(response);
    const results = [];
    document(".search-details").each((index, element) => {
        var url;
        const [, itemValue, itemValue2] = document(element).find("a").first().text().trim().match(/^(.*?)\s*(?:\(?\s*(\d{4})(?:\s*-\s*\d{0,4})?\s*\)?)?\s*$/) || [];
        const url3 = (url = document(element).find("a").attr("href")) == null ? void 0 : url.split("/")[4];
        !itemValue || !url3 || results.push({ title: itemValue, year: itemValue2 ? parseInt(itemValue2, 10) : void 0, url: url3 });
    });
    const item = results.find(item => item && fsharetvProcessData2(context.media, item.title, item.year))?.url;
    if (!item) {
        throw new ScraperError("No watchable item found");
    }
    context.progress(60);
    const queryParams = await context.proxiedFetcher("/info2?v=8", { method: "POST", body: new URLSearchParams({ z: JSON.stringify([{ s: item, t: "movie" }]) }), baseUrl: mp4hydraBaseUrl });
    if (!queryParams.playlist[0].src || !queryParams.servers) {
        throw new ScraperError("No watchable item found");
    }
    context.progress(80);
    const results2 = [];
    [queryParams.servers[queryParams.servers.auto], ...Object.values(queryParams.servers).filter(item => item !== queryParams.servers[queryParams.servers.auto] && item !== queryParams.servers.auto)].forEach((item, index3) => results2.push({ embedId: "mp4hydra-" + (index3 + 1), url: "" + item + queryParams.playlist[0].src + "|" + queryParams.playlist[0].label }));
    context.progress(90);
    return {
        embeds: results2
    };
}
const mp4hydraProviderConfig = {
    id: "mp4hydra",
    name: "Mp4Hydra \uD83D\uDC0C",
    rank: 3,
    disabled: true,
    flags: ["cors-allowed"],
    scrapeMovie: scrapeMp4hydra,
    scrapeShow: scrapeMp4hydra
};
const mp4hydraProvider = createSourceProvider(mp4hydraProviderConfig);
const nepuBaseUrl = "https://nscrape.andresdev.org/api";
async function scrapeNepu(context) {
    const tmdbId2 = context.media.tmdbId;
    let temporaryValue;
    if (context.media.type === "movie") {
        temporaryValue = nepuBaseUrl + "/get-stream?tmdbId=" + tmdbId2;
    }
    else {
        ;
        temporaryValue = nepuBaseUrl + "/get-show-stream?tmdbId=" + tmdbId2 + "&season=" + context.media.season.number + "&episode=" + context.media.episode.number;
    }
    const response = await context.proxiedFetcher(temporaryValue);
    if (!response.success || !response.rurl) {
        throw new ScraperError("No stream found");
    }
    const stream = {
        id: "nepu",
        type: "hls",
        playlist: response.rurl,
        flags: ["cors-allowed"],
        captions: []
    };
    return {
        stream: [stream],
        embeds: []
    };
}
const nepuProviderConfig = {
    id: "nepu",
    name: "Nepu \uD83D\uDCA7",
    rank: 201,
    disabled: true,
    flags: ["cors-allowed"],
    scrapeMovie: scrapeNepu,
    scrapeShow: scrapeNepu
};
const nepuProvider = createSourceProvider(nepuProviderConfig);
const qstreamBaseUrl = "https://friday123.vercel.app";
async function scrapeQstream(context) {
    const response = await context.proxiedFetcher("/search", { baseUrl: qstreamBaseUrl, query: { q: context.media.title } });
    const item = response.items.find(item => {
        const parts = "2|0|3|4|1".split("|");
        let value = 0;
        for (;;) {
            switch (parts[value++]) {
                case "0":
                    if (context.media.type
                        === "show"
                        &&
                            item.type
                                !==
                                    "TV") {
                        return false;
                    }
                    continue;
                case "1": return true;
                case "2":
                    if (context.media.type === "movie" &&
                        item.type
                            !== "Movie") {
                        return false;
                    }
                    continue;
                case "3":
                    if (!fsharetvProcessData(item.title, context.media.title)) {
                        return false;
                    }
                    continue;
                case "4":
                    if (item.year &&
                        Number(item.year)
                            !==
                                context.media.releaseYear) {
                        return false;
                    }
                    continue;
            }
            break;
        }
    });
    if (!item) {
        throw new ScraperError("No watchable item found");
    }
    let temporaryValue;
    if (context.media.type === "movie") {
        const result = {
            id: item.id
        };
        const requestOptions = {
            baseUrl: qstreamBaseUrl,
            query: result
        };
        temporaryValue = (await context.proxiedFetcher("/details", requestOptions)).episodeId;
    }
    else if (context.media.type
        === "show") {
        const media2 = context.media;
        const result2 = {
            id: item.id
        };
        const requestOptions2 = {
            baseUrl: qstreamBaseUrl,
            query: result2
        };
        const response2 = await context.proxiedFetcher("/seasons", requestOptions2);
        const match = response2.seasons.find(item => item.number === media2.season.number);
        if (!match) {
            throw new ScraperError("Season not found");
        }
        const result3 = {
            season: match.id,
            id: item.id
        };
        const requestOptions3 = {
            baseUrl: qstreamBaseUrl,
            query: result3
        };
        const response3 = await context.proxiedFetcher("/episodes", requestOptions3);
        const match2 = response3.episodes.find(item => item.number === media2.episode.number);
        if (!match2) {
            throw new ScraperError("Episode not found");
        }
        temporaryValue = match2.id;
    }
    if (!temporaryValue) {
        throw new ScraperError("Failed to get episode id");
    }
    const result4 = {
        episode: temporaryValue
    };
    const requestOptions4 = {
        baseUrl: qstreamBaseUrl,
        query: result4
    };
    const response4 = await context.proxiedFetcher("/servers", requestOptions4);
    const items3 = response4.sort((left, right) => {
        ;
        {
            const items2 = ["VidStr Server", "UpCloud Server", "AKCloud Server"];
            return items2.indexOf(left.server) - items2.indexOf(right.server);
        }
    }).map(item => {
        let value = "";
        if (item.server
            === "Vidcloud Server") {
            value = "vidstr";
        }
        else {
            return null;
        }
        return {
            embedId: value,
            url: item.source
        };
    }).filter(Boolean);
    if (items3.length
        ===
            0) {
        throw new ScraperError("No watchable embeds found");
    }
    return {
        embeds: items3
    };
}
const qstreamProviderConfig = {
    id: "qstream",
    name: "Nefaria \uD83D\uDCAB",
    rank: 893,
    disabled: true,
    flags: ["cors-allowed"],
    scrapeMovie: scrapeQstream,
    scrapeShow: scrapeQstream
};
const qstreamProvider = createSourceProvider(qstreamProviderConfig);
const rutubeBaseUrl = "https://rutube.ru/api";
function rutubeMapQuality(input) {
    const result = {
        "344": "360",
        "456": "480",
        "688": "720"
    };
    const value = result;
    if (value[input]) {
        return value[input];
    }
    const results = [360, 480, 720, 1080, 2160];
    let value5 = results[0];
    let value6 = Math.abs(input - value5);
    for (const item of results) {
        const value7 = Math.abs(input - item);
        if (value7 < value6) {
            (value6 = value7, value5 = item);
        }
    }
    return value6 > 100 ? "unknown" : value5.toString();
}
async function scrapeRutube(context) {
    const title2 = context.media.title;
    const value = rutubeBaseUrl + "/search/video/?query=" + encodeURIComponent(title2);
    const response = await context.proxiedFetcher(value);
    if (!response.results || response.results.length === 0) {
        throw new ScraperError("No results found");
    }
    const item = response.results.find(item => item.title.toLowerCase().includes(context.media.title.toLowerCase()));
    if (!item) {
        throw new ScraperError("No matching video found");
    }
    const id2 = item.id;
    if (!id2) {
        ;
        throw new ScraperError("No video ID found");
    }
    const url3 = rutubeBaseUrl + "/play/options/" + id2;
    const response2 = await context.proxiedFetcher(url3);
    const value7 = response2.video_balancer?.m3u8;
    if (!value7) {
        throw new ScraperError("No m3u8 url found");
    }
    const response3 = await context.proxiedFetcher(value7);
    const value8 = st.parse(response3);
    const result = {};
    const captions = ["360", "480", "720", "1080", "4k"];
    if ("isMasterPlaylist" in value8
        && value8.isMasterPlaylist && ((value8.variants || []).forEach(item => {
        if (item.uri) {
            let value;
            if (item.resolution && item.resolution.height)
                value = rutubeMapQuality(item.resolution.height);
            else if (item.bandwidth) {
                const value10 = item.bandwidth;
                let value11;
                value10 >= 8000000 ? value11 = "1080" : value10 >=
                    5000000
                    ? value11 = "720" : value10 >= 2500000 ? value11 = "480" : value10 >= 1000000 ? value11 = "360" : value11 = "240", captions.includes(value11) ? value = value11 : value = "unknown";
            }
            else
                value = "unknown";
            const normalizedValue = value.replace("p", "");
            captions.includes(normalizedValue) && (result[value] = { type: "hls", url: buildProxiedHlsUrl(item.uri, context.features) });
        }
    })),
        Object.keys(result).length
            ===
                0) {
        throw new ScraperError("No qualities found in m3u8");
    }
    const value9 = Object.keys(result).reduce((accumulator, item) => {
        const items = ["360", "480", "720", "1080", "4k"];
        const value = items.indexOf(accumulator) || -1;
        const value11 = items.indexOf(item) || -1;
        return value11 > value
            ? item : accumulator;
    }, Object.keys(result)[0] || "");
    const url4 = result[value9]?.url;
    if (!url4) {
        throw new ScraperError("No valid stream URL found");
    }
    const stream = {
        id: "primary",
        type: "hls",
        playlist: url4,
        flags: ["cors-allowed"],
        captions: []
    };
    return {
        embeds: [],
        stream: [stream]
    };
}
const rutubeProviderConfig = {
    id: "rutube",
    name: "RuTube \uD83E\uDD91(Russian)",
    rank: 171,
    disabled: true,
    flags: ["cors-allowed"],
    scrapeMovie: scrapeRutube,
    scrapeShow: scrapeRutube
};
const rutubeProvider = createSourceProvider(rutubeProviderConfig);
const soapyBaseUrl = "https://soapy.to";
const soapyValue = ["romio"];
async function soapyLookupEpisode(context, argument2) {
    const results = [];
    for (const item of soapyValue) {
        const value = context.media.type === "movie" ? soapyBaseUrl + "/embed/movies.php?tmdbid=" + argument2 + "&player=" + item : soapyBaseUrl + "/embed/series.php?id=" + argument2 + "&season=" + context.media.season.number + "&episode=" + context.media.episode.number + "&player=" + item;
        const response = await context.proxiedFetcher(value);
        const document = loadHtml(response);
        const url = document("iframe").attr("src");
        if (url) {
            const embed = {
                embedId: "vidcloud",
                url: url
            };
            results.push(embed);
        }
    }
    if (results.length
        ===
            0) {
        throw new ScraperError("No embeds found");
    }
    return {
        embeds: results
    };
}
async function scrapeSoapyMovie(context) {
    return { bQHHp: function (argument1, argument2, argument3) {
            return argument1(argument2, argument3);
        } }.bQHHp(soapyLookupEpisode, context, context.media.tmdbId);
}
async function scrapeSoapyShow(context) {
    return soapyLookupEpisode(context, context.media.tmdbId);
}
const soapySourceProvider = createSourceProvider({ id: "soapy", name: "Soapy \uD83E\uDDFC", disabled: true, rank: 874, flags: ["cors-allowed"], scrapeMovie: scrapeSoapyMovie, scrapeShow: scrapeSoapyShow });
const tugaflixBaseUrl = "https://tugaflix.love/";
function tugaflixExtractValue(input) {
    const results = [];
    const document = loadHtml(input);
    document(".items .poster").each((index, element) => {
        var value;
        const match = document(element).find("a");
        const url = match.attr("href");
        const [, itemValue, itemValue2] = ((value = match.attr("title")) == null ? void 0 : value.match(/^(.*?)\s*(?:\((\d{4})\))?\s*$/)) || [];
        !itemValue || !url || results.push({ title: itemValue, year: itemValue2 ? parseInt(itemValue2, 10) : void 0, url: url });
    });
    return results;
}
async function scrapeTugaflixMovie(context) {
    const response = tugaflixExtractValue(await context.proxiedFetcher("/filmes/", { baseUrl: tugaflixBaseUrl, query: { s: context.media.title } }));
    if (response.length === 0) {
        throw new ScraperError("No watchable item found");
    }
    const item = response.find(item => item && fsharetvProcessData2(context.media, item.title, item.year))?.url;
    if (!item) {
        throw new ScraperError("No watchable item found");
    }
    context.progress(50);
    const result = {
        play: ""
    };
    const queryParams = await context.proxiedFetcher(item, { method: "POST", body: new URLSearchParams(result) });
    const document = loadHtml(queryParams);
    const streams = [];
    for (const temporaryValue3 of document(".play a")) {
        const value = document(temporaryValue3).attr("href");
        if (!value) {
            continue;
        }
        const url = await context.proxiedFetcher.full(value.startsWith("https://") ? value : "https://" + value);
        const document3 = loadHtml(url.body)("a:contains(\"Download Filme\")").attr("href");
        if (!document3) {
            continue;
        }
        if (document3.includes("streamtape")) {
            const embed = {
                embedId: "streamtape",
                url: document3
            };
            streams.push(embed);
        }
        else if (document3.includes("dood")) {
            const embed3 = {
                embedId: "dood",
                url: document3
            };
            streams.push(embed3);
        }
    }
    context.progress(90);
    return {
        embeds: streams
    };
}
async function scrapeTugaflixShow(context) {
    const response = tugaflixExtractValue(await context.proxiedFetcher("/series/", { baseUrl: tugaflixBaseUrl, query: { s: context.media.title } }));
    if (response.length === 0) {
        throw new ScraperError("No watchable item found");
    }
    const item = response.find(item => item && fsharetvProcessData2(context.media, item.title, item.year))?.url;
    if (!item) {
        throw new ScraperError("No watchable item found");
    }
    context.progress(50);
    const value = context.media.season.number < 10 ? "0" + context.media.season.number : context.media.season.number.toString();
    const value4 = context.media.episode.number
        <
            10
        ? "0" + context.media.episode.number : context.media.episode.number.toString();
    const result2 = { ["S" + value + "E" + value4]: "" };
    const queryParams = await context.proxiedFetcher(item, { method: "POST", body: new URLSearchParams(result2) });
    const document = loadHtml(queryParams)("iframe[name=\"player\"]").attr("src");
    if (!document) {
        throw new Error("Failed to find iframe");
    }
    const result = {
        submit: ""
    };
    const queryParams2 = await context.proxiedFetcher(document.startsWith("https:") ? document : "https:" + document, { method: "POST", body: new URLSearchParams(result) });
    const streams = [];
    const document3 = loadHtml(queryParams2)("a:contains(\"Download Episodio\")").attr("href");
    if (document3 != null && document3.includes("streamtape")) {
        const embed = {
            embedId: "streamtape",
            url: document3
        };
        streams.push(embed);
    }
    else if (document3 != null && document3.includes("dood")) {
        const embed3 = {
            embedId: "dood",
            url: document3
        };
        streams.push(embed3);
    }
    context.progress(90);
    return {
        embeds: streams
    };
}
const tugaflixSourceProvider = createSourceProvider({ id: "tugaflix", name: "Tugaflix \uD83D\uDC2F", rank: 70, flags: ["ip-locked"], scrapeMovie: scrapeTugaflixMovie, scrapeShow: scrapeTugaflixShow });
const videasyBaseUrl = "https://easy.aether.cx";
function videasyProcessData(context) {
    const value = context.media.type === "movie" ? "movie/" + context.media.tmdbId : "tv/" + context.media.tmdbId + "/" + context.media.season.number + "/" + context.media.episode.number;
    return videasyBaseUrl + "/" + value + "?provider=cdn&single=1";
}
function videasyMapQuality(input) {
    const value = (input == null ? void 0 : input.toLowerCase()) ?? "";
    if (value.includes("4k") || value.includes("2160")) {
        return 2160;
    }
    const match = value.match(/(\d{3,4})/u);
    return match ?
        Number(match[1])
        : 0;
}
async function scrapeVideasy(context) {
    const response = await context.fetcher(videasyProcessData(context));
    let temporaryValue;
    if (typeof response !== "string") {
        temporaryValue = response;
    }
    else {
        try {
            temporaryValue = JSON.parse(response);
        }
        catch {
            throw new ScraperError("VideoEasy API returned a non-JSON response");
        }
    }
    const value = new Set;
    const value3 = new Set;
    const streams = [];
    if ((temporaryValue.sources ?? []).filter(item => typeof item.url == "string" && item.url.includes(".m3u8")).sort((left, right) => videasyMapQuality(right.quality) - videasyMapQuality(left.quality)).forEach(item => {
        const url = item.url;
        if (value.has(url))
            return;
        value.add(url);
        const value = mapVideasyQuality(item.quality);
        if (!value || value3.has(value))
            return;
        value3.add(value);
        const result = {};
        result.embedId = value, result.url = url, streams.push(result);
    }),
        streams.length
            ===
                0) {
        throw new ScraperError("No VideoEasy CDN streams found");
    }
    return {
        embeds: streams
    };
}
const videasyProviderConfig = {
    id: "videasy",
    name: "Videasy \uD83E\uDE84",
    rank: 913,
    disabled: true,
    flags: ["cors-allowed"],
    scrapeMovie: scrapeVideasy,
    scrapeShow: scrapeVideasy
};
const videasyProvider = createSourceProvider(videasyProviderConfig);
const vidoraBaseUrl = "https://vidora.su";
const vidoraBaseUrl2 = "https://scraper.aether.mom/api/scrape";
const vidoraValue = "6HkTYS+BIsj9Arv9m5WPvw==";
async function scrapeVidora(context) {
    const type2 = context.media.type;
    const tmdbId2 = context.media.tmdbId;
    const value = type2 === "show" ? context.media.season.number : void 0;
    const value5 = type2 === "show" ? context.media.episode.number : void 0;
    const requestUrl = "https://vidora.su/" + (type2 === "show" ? "tv/" + tmdbId2 + "/" + value + "/" + value5 : "movie/" + tmdbId2);
    const url = vidoraBaseUrl2 + "?url=" + encodeURIComponent(requestUrl) + "&waitFor=.m3u8";
    const requestOptions = {
        Referer: vidoraBaseUrl
    };
    const requestOptions2 = {
        headers: requestOptions
    };
    const response = await context.proxiedFetcher(url, requestOptions2);
    const token = CryptoJS.AES.decrypt(response.data, vidoraValue);
    const data = JSON.parse(token.toString(CryptoJS.enc.Utf8));
    const item = data.requests.find(item => item.url.includes(".m3u8"));
    if (!item) {
        throw new ScraperError("No m3u8 url found in response");
    }
    const requestOptions3 = {
        Referer: "https://vidora.su/",
        Origin: "https://vidora.su"
    };
    const url3 = requestOptions3;
    return { embeds: [], stream: [{ id: "primary", type: "hls", playlist: buildProxiedHlsUrl(item.url, context.features, url3), flags: ["cors-allowed"], captions: [], headers: url3 }] };
}
const vidoraProviderConfig = {
    id: "vidora",
    name: "Vidora \uD83C\uDF3F",
    rank: 826,
    disabled: true,
    flags: ["cors-allowed"],
    scrapeMovie: scrapeVidora,
    scrapeShow: scrapeVidora
};
function vidoraDecodePayload(input) {
    return String.fromCharCode(input);
}
function vidsrcProcessData(input) {
    const value = input.split(vidoraDecodePayload(61));
    let value7 = "";
    const value8 = vidoraDecodePayload(120);
    for (const item of value) {
        let value9 = "";
        for (let value10 = 0; value10 < item.length; value10++)
            value9 += item[value10]
                === value8
                ?
                    vidoraDecodePayload(49)
                :
                    vidoraDecodePayload(48);
        const numericValue = parseInt(value9, 2);
        value7 += vidoraDecodePayload(numericValue);
    }
    return value7.substring(0, value7.length
        -
            1);
}
function vidsrcProcessData2(input, argument2) {
    input = input.replace(/\+/g, "#");
    input = input.replace(/#/g, "+");
    const value = "xx??x?=xx?xx?=";
    let url = Number(vidsrcProcessData(value)) * argument2;
    url += vidoraValue2.length / 2;
    const value4 = vidoraValue2.substr(url * 2) + vidoraValue2.substr(0, url * 2);
    return input.replace(/[A-Za-z]/g, argument1 => value4.charAt(vidoraValue2.indexOf(argument1)));
}
function vidsrcProcessData3(input) {
    return input.substr(0, 2) === "#1" ? vidoraValue3.d(vidsrcProcessData2(input.substr(2), -1)) : input.substr(0, 2) === "#0" ? vidoraValue3.d(input.substr(2)) : input;
}
function vidsrcDecodePayload(input, argument2) {
    let value = input.substring(2);
    for (let value4 = 4; value4 >= 0; value4--)
        if (argument2["bk" + value4]) {
            const characterCode = argument1 => btoa(encodeURIComponent(argument1).replace(/%([0-9A-F]{2})/g, (argument12, argument23) => String.fromCharCode(parseInt(argument23, 16))));
            value = value.replace(argument2.file3_separator
                +
                    characterCode(argument2["bk" + value4]), "");
        }
    const items = argument1 => decodeURIComponent(atob(argument1).split("").map(item => "%" + ("00" + item.charCodeAt(0).toString(16)).slice(-2)).join(""));
    return items(value);
}
const vidoraProvider = createSourceProvider(vidoraProviderConfig);
const vidoraValue2 = String.fromCharCode(65, 66, 67, 68, 69, 70, 71, 72, 73, 74, 75, 76, 77, 97, 98, 99, 100, 101, 102, 103, 104, 105, 106, 107, 108, 109, 78, 79, 80, 81, 82, 83, 84, 85, 86, 87, 88, 89, 90, 110, 111, 112, 113, 114, 115, 116, 117, 118, 119, 120, 121, 122);
const vidoraValue3 = { _keyStr: vidoraValue2 + "0123456789+/=", e(a) {
        let c = "";
        let t;
        let r;
        let d;
        let o;
        let f;
        let i;
        let W;
        let b = 0;
        for (a = vidoraValue3._ue(a); b < a.length;)
            (t = a.charCodeAt(b++), r = a.charCodeAt(b++), d = a.charCodeAt(b++), o =
                t
                    >>
                        2, f =
                (t
                    &
                        3)
                    << 4
                    | r
                        >>
                            4, i =
                (r
                    &
                        15)
                    << 2
                    | d
                        >>
                            6, W =
                d
                    &
                        63, Number.isNaN(r) ? (i = 64, W = 64) : Number.isNaN(d) && (W = 64), c +=
                this._keyStr.charAt(o) + this._keyStr.charAt(f)
                    +
                        this._keyStr.charAt(i) +
                    this._keyStr.charAt(W));
        return c;
    }, d(a) {
        let c = "";
        let t;
        let r;
        let d;
        let o;
        let f;
        let i;
        let W;
        let b = 0;
        for (a = a.replace(/[^A-Za-z0-9+/=]/g, ""); b < a.length;) {
            const s = "1|4|6|0|2|3|7|5|9|8".split("|");
            let u = 0;
            for (;;) {
                switch (s[u++]) {
                    case "0":
                        W = this._keyStr.indexOf(a.charAt(b++));
                        continue;
                    case "1":
                        o = this._keyStr.indexOf(a.charAt(b++));
                        continue;
                    case "2":
                        t =
                            o << 2
                                | f
                                    >>
                                        4;
                        continue;
                    case "3":
                        r = (f
                            &
                                15) <<
                            4
                            | i >> 2;
                        continue;
                    case "4":
                        f = this._keyStr.indexOf(a.charAt(b++));
                        continue;
                    case "5":
                        c +=
                            vidoraDecodePayload(t);
                        continue;
                    case "6":
                        i = this._keyStr.indexOf(a.charAt(b++));
                        continue;
                    case "7":
                        d =
                            (i
                                &
                                    3) <<
                                6 |
                                W;
                        continue;
                    case "8":
                        W !== 64 && (c +=
                            vidoraDecodePayload(d));
                        continue;
                    case "9":
                        i
                            !==
                                64
                            && (c +=
                                vidoraDecodePayload(r));
                        continue;
                }
                break;
            }
        }
        c = vidoraValue3._ud(c);
        return c;
    }, _ue(a) {
        a = a.replace(/\r\n/g, `
`);
        let t = "";
        for (let r = 0; r
            <
                a.length; r++) {
            const d = a.charCodeAt(r);
            d
                <
                    128
                ? t +=
                    vidoraDecodePayload(d) : d > 127 &&
                d
                    <
                        2048 ? (t += vidoraDecodePayload(d >> 6
                |
                    192), t +=
                vidoraDecodePayload(d
                    &
                        63 |
                    128)) : (t +=
                vidoraDecodePayload(d
                    >>
                        12 |
                    224), t +=
                vidoraDecodePayload(d >> 6
                    &
                        63 |
                    128), t += vidoraDecodePayload(d
                &
                    63 |
                128));
        }
        return t;
    }, _ud(a) {
        let c = "";
        let t = 0;
        let r;
        let d;
        let o;
        for (; t < a.length;)
            if (r = a.charCodeAt(t),
                r
                    <
                        128) {
                c +=
                    vidoraDecodePayload(r), t++;
            }
            else if (r
                >
                    191
                &&
                    r
                        <
                            224) {
                d = a.charCodeAt(t
                    +
                        1), c +=
                    vidoraDecodePayload((r & 31)
                        <<
                            6
                        | d & 63), t += 2;
            }
            else {
                d = a.charCodeAt(t + 1), o = a.charCodeAt(t + 2), c += vidoraDecodePayload((r & 15)
                    <<
                        12 | (d
                    &
                        63) <<
                    6 | o
                    &
                        63), t += 3;
            }
        return c;
    } };
async function scrapeVidsrc(context) {
    const imdbId2 = context.media.imdbId;
    if (!imdbId2) {
        throw new ScraperError("IMDb ID not found");
    }
    const value = context.media.type === "show";
    let url;
    let url2;
    if (value) {
        const media2 = context.media;
        url = media2.season?.number;
        url2 = media2.episode?.number;
    }
    const url3 = value ? "https://vidsrc.net/embed/tv?imdb=" + imdbId2 + "&season=" + url + "&episode=" + url2 : "https://vidsrc.net/embed/" + imdbId2;
    context.progress(10);
    const requestOptions = {
        Referer: "https://vidsrc.net/",
        "User-Agent": "Mozilla/5.0"
    };
    const requestOptions2 = {
        headers: requestOptions
    };
    const response = await context.proxiedFetcher(url3, requestOptions2);
    context.progress(30);
    const match = response.match(/<iframe[^>]*id="player_iframe"[^>]*src="([^"]*)"[^>]*>/);
    if (!match) {
        throw new ScraperError("Initial iframe not found");
    }
    const value9 = match[1].startsWith("//") ? "https:" + match[1] : match[1];
    context.progress(50);
    const requestOptions3 = {
        Referer: url3,
        "User-Agent": "Mozilla/5.0"
    };
    const requestOptions4 = {
        headers: requestOptions3
    };
    const response2 = await context.proxiedFetcher(value9, requestOptions4);
    const match6 = response2.match(/src\s*:\s*['"]([^'"]+)['"]/);
    if (!match6) {
        throw new ScraperError("prorcp iframe not found");
    }
    const url4 = match6[1].startsWith("/") ? "https://cloudnestra.com" + match6[1] : match6[1];
    context.progress(70);
    const requestOptions5 = {
        Referer: value9,
        "User-Agent": "Mozilla/5.0"
    };
    const requestOptions6 = {
        headers: requestOptions5
    };
    const response3 = await context.proxiedFetcher(url4, requestOptions6);
    const parts = response3.split("<script");
    let value10 = "";
    for (const item of parts)
        if (item.includes("Playerjs")) {
            value10 = item;
            break;
        }
    if (!value10) {
        throw new ScraperError("No Playerjs config found");
    }
    const match7 = value10.match(/file\s*:\s*['"]([^'"]+)['"]/);
    if (!match7) {
        throw new ScraperError("No file field in Playerjs");
    }
    let url5 = match7[1];
    if (!url5.includes(".m3u8")) {
        ;
        {
            const data = JSON.parse(vidsrcProcessData3("#1RyJzl3JYmljm0mkJWOGYWNyI6MfwVNGYXmj9uQj5tQkeYIWoxLCJXNkawOGF5QZ9sQj1YIWowLCJXO20VbVJ1OZ11QGiSlni0QG9uIn19"));
            url5 = vidsrcDecodePayload(url5, data);
        }
    }
    context.progress(90);
    const result = {
        referer: "https://cloudnestra.com/",
        origin: "https://cloudnestra.com"
    };
    const url6 = result;
    return { stream: [{ id: "vidsrc-cloudnestra", type: "hls", playlist: buildProxiedHlsUrl(url5, void 0, url6), flags: ["cors-allowed"], captions: [] }], embeds: [] };
}
const vidsrcProviderConfig = {
    id: "vidsrc",
    name: "Cloudnestra \u26A1\uFE0F",
    rank: 880,
    flags: [],
    scrapeMovie: scrapeVidsrc,
    scrapeShow: scrapeVidsrc
};
const vidsrcProvider = createSourceProvider(vidsrcProviderConfig);
const vidsrcwtfBaseUrl = "https://dezzu370xol.com";
async function scrapeVidsrcwtfMovie(context) {
    const imdbId2 = context.media.imdbId;
    if (!imdbId2) {
        throw new ScraperError("IMDb ID not found");
    }
    const requestOptions = {
        Referer: "https://www.vidsrc.wtf/"
    };
    const requestOptions2 = {
        baseUrl: vidsrcwtfBaseUrl,
        headers: requestOptions
    };
    const response = await context.proxiedFetcher("/play/" + imdbId2, requestOptions2);
    const match = response.match(/let pc = ({.*});/s);
    if (!match) {
        throw new Error("Failed to find player config");
    }
    const data = JSON.parse(match[1]);
    const response2 = await context.proxiedFetcher(data.file, { method: "POST", headers: { "X-CSRF-TOKEN": data.key, Referer: vidsrcwtfBaseUrl + "/", Origin: vidsrcwtfBaseUrl, "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:141.0) Gecko/20100101 Firefox/141.0", "Content-type": "application/x-www-form-urlencoded" } });
    const value = response2[1];
    if (!value) {
        throw new Error("No english source found");
    }
    const value3 = value.file.startsWith("~") ? value.file.substring(1) : value.file;
    const requestOptions3 = {
        baseUrl: vidsrcwtfBaseUrl,
        method: "POST",
        headers: {}
    };
    requestOptions3.headers["X-CSRF-TOKEN"] = data.key;
    requestOptions3.headers.Referer = vidsrcwtfBaseUrl + "/play/" + imdbId2;
    requestOptions3.headers.Origin = vidsrcwtfBaseUrl;
    requestOptions3.headers["User-Agent"] = "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:141.0) Gecko/20100101 Firefox/141.0";
    requestOptions3.headers["Content-type"] = "application/x-www-form-urlencoded";
    const playlistUrl = await context.proxiedFetcher("/playlist/" + value3 + ".txt", requestOptions3);
    const stream = {
        id: "primary",
        type: "hls",
        playlist: playlistUrl,
        flags: [],
        captions: []
    };
    return {
        embeds: [],
        stream: [stream]
    };
}
async function scrapeVidsrcwtfShow(context) {
    const imdbId2 = context.media.imdbId;
    if (!imdbId2) {
        throw new ScraperError("IMDb ID not found");
    }
    const requestOptions = {
        Referer: "https://www.vidsrc.wtf/"
    };
    const requestOptions2 = {
        baseUrl: vidsrcwtfBaseUrl,
        headers: requestOptions
    };
    const response = await context.proxiedFetcher("/play/" + imdbId2, requestOptions2);
    let match = response.match(/let pc = ({.*});/s);
    if (!match && (match = response.match(/new HDVBPlayer\((.*)\);/s)), !match) {
        throw new Error("Failed to find player config");
    }
    const data = JSON.parse(match[1]);
    const playlistResponse = await context.proxiedFetcher(data.file.startsWith("/playlist") ? data.file : "/playlist/" + data.file, { baseUrl: vidsrcwtfBaseUrl, method: "POST", headers: { "X-CSRF-TOKEN": data.key, Referer: vidsrcwtfBaseUrl + "/", Origin: vidsrcwtfBaseUrl, "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:141.0) Gecko/20100101 Firefox/141.0", "Content-type": "application/x-www-form-urlencoded" } });
    const media2 = context.media;
    const item = playlistResponse.find(item => item.title === "Season " + media2.season.number);
    if (!item) {
        throw new ScraperError("Season not found");
    }
    const match4 = item.folder.find(item => item.episode === "" + media2.episode.number);
    if (!match4) {
        throw new ScraperError("Episode not found");
    }
    const match5 = match4.folder.find(item => item.title === "English");
    if (!match5) {
        throw new ScraperError("No english source found for episode");
    }
    let file2 = match5.file;
    if (file2.startsWith("~")) {
        (file2 = file2.substring(1));
    }
    const requestOptions3 = {
        baseUrl: vidsrcwtfBaseUrl,
        method: "POST",
        headers: {}
    };
    requestOptions3.headers["X-CSRF-TOKEN"] = data.key;
    requestOptions3.headers.Referer = vidsrcwtfBaseUrl + "/play/" + imdbId2;
    requestOptions3.headers.Origin = vidsrcwtfBaseUrl;
    requestOptions3.headers["User-Agent"] = "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:141.0) Gecko/20100101 Firefox/141.0";
    requestOptions3.headers["Content-type"] = "application/x-www-form-urlencoded";
    const playlistUrl = await context.proxiedFetcher("/playlist/" + file2 + ".txt", requestOptions3);
    const stream = {
        id: "primary",
        type: "hls",
        playlist: playlistUrl,
        flags: [],
        captions: []
    };
    return {
        embeds: [],
        stream: [stream]
    };
}
const vidsrcwtfProviderConfig = {
    id: "vidsrcwtf",
    name: "VidSrcWT \u2604\uFE0F",
    rank: 800,
    disabled: true,
    flags: ["cors-allowed"],
    scrapeMovie: scrapeVidsrcwtfMovie,
    scrapeShow: scrapeVidsrcwtfShow
};
const vidsrcwtfProvider = createSourceProvider(vidsrcwtfProviderConfig);
const vidsrcwtfBaseUrl2 = "https://yflix.to";
const vidsrcwtfValue = vidsrcwtfBaseUrl2 + "/ajax";
const vidsrcwtfBaseUrl3 = "https://enc-dec.app/api";
const vidsrcwtfValue2 = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/137.0.0.0 Safari/537.36";
async function vidsrcwtfFetchData(context, argument2) {
    const requestOptions = {
        "User-Agent": vidsrcwtfValue2
    };
    const result = {
        text: argument2
    };
    const response = await context.proxiedFetcher("enc-movies-flix", { baseUrl: vidsrcwtfBaseUrl3, method: "GET", headers: requestOptions, query: result });
    if (!(response != null && response.result)) {
        throw new ScraperError("yFlix: enc failed");
    }
    return response.result;
}
async function vidsrcwtfDecryptPayload(context, argument2) {
    const requestOptions = {
        "Content-Type": "application/json",
        "User-Agent": vidsrcwtfValue2
    };
    const result = {
        text: argument2
    };
    const response = await context.proxiedFetcher("dec-movies-flix", { baseUrl: vidsrcwtfBaseUrl3, method: "POST", headers: requestOptions, body: JSON.stringify(result) });
    if (!(response != null && response.result)) {
        throw new ScraperError("yFlix: decrypt failed");
    }
    return response.result;
}
async function vidsrcwtfDecryptPayload2(context, argument2) {
    const response = await context.proxiedFetcher("dec-rapid", { baseUrl: vidsrcwtfBaseUrl3, method: "POST", headers: { "Content-Type": "application/json", "User-Agent": vidsrcwtfValue2 }, body: JSON.stringify({ text: argument2, agent: vidsrcwtfValue2 }) });
    if (!(response != null && response.result)) {
        throw new ScraperError("Rapid decrypt failed");
    }
    return response.result;
}
function vidsrcwtfProcessData(input) {
    const value = "2|0|7|3|4|6|5|1".split("|");
    let value3 = 0;
    for (;;) {
        switch (value[value3++]) {
            case "0":
                if (input &&
                    typeof input.result
                        ===
                            "string") {
                    return input.result;
                }
                continue;
            case "1": throw new ScraperError("yFlix: unexpected AJAX response");
            case "2":
                if (typeof input
                    === "string") {
                    return input;
                }
                continue;
            case "3":
                if (input &&
                    typeof input.html
                        === "string") {
                    return input.html;
                }
                continue;
            case "4":
                if (input && typeof input.data === "string") {
                    return input.data;
                }
                continue;
            case "5":
                if (input && typeof input.response == "string") {
                    return input.response;
                }
                continue;
            case "6":
                if (input && input.data &&
                    typeof input.data.html
                        === "string") {
                    return input.data.html;
                }
                continue;
            case "7":
                if (input && input.result && typeof input.result.html === "string") {
                    return input.result.html;
                }
                continue;
        }
        break;
    }
}
async function vidsrcwtfFetchData2(context, argument2) {
    const result = {
        text: argument2
    };
    const response = await context.proxiedFetcher("parse-html", { baseUrl: vidsrcwtfBaseUrl3, method: "POST", headers: { "Content-Type": "application/json", "User-Agent": vidsrcwtfValue2 }, body: JSON.stringify(result) });
    if (!(response != null && response.result)) {
        throw new ScraperError("yFlix: parse-html failed");
    }
    return response.result;
}
function yflixProcessData(input) {
    const value = "3|4|1|0|2".split("|");
    let value3 = 0;
    for (;;) {
        switch (value[value3++]) {
            case "0":
                if (input &&
                    typeof input.result
                        === "string") {
                    return input.result;
                }
                continue;
            case "1":
                if (input &&
                    typeof input.link
                        === "string") {
                    return input.link;
                }
                continue;
            case "2": throw new ScraperError("yFlix: invalid embed url payload");
            case "3":
                if (typeof input == "string") {
                    return input;
                }
                continue;
            case "4":
                if (input &&
                    typeof input.url
                        === "string") {
                    return input.url;
                }
                continue;
        }
        break;
    }
}
async function yflixFetchData(context, key) {
    const value = vidsrcwtfBaseUrl2 + "/browser?keyword=" + encodeURIComponent(key);
    const result = {
        "User-Agent": vidsrcwtfValue2
    };
    const requestOptions = {
        headers: result
    };
    const response = await context.proxiedFetcher(value, requestOptions);
    return loadHtml(response);
}
function yflixProcessData2(input) {
    return input.replace(/\s+/g, " ").trim().toLowerCase();
}
function yflixParseHtml(input, argument2, argument3) {
    const value = input(".inner");
    for (const item of value.toArray()) {
        const value3 = input(item);
        const match = yflixProcessData2(value3.find(".info .title").text());
        const match2 = Number((value3.find(".metadata span").eq(1).text() || "").replace(/[^\d]/g, ""));
        if (match &&
            yflixProcessData2(argument2) === match &&
            match2 === argument3) {
            return value3;
        }
    }
    return null;
}
function yflixParseHtml2(input, argument2) {
    const value = input(".inner");
    for (const item of value.toArray()) {
        const value3 = input(item);
        const match = yflixProcessData2(value3.find(".info .title").text());
        const items = value3.find(".metadata span").map((item, index) => input(index).text()).get().join(" ");
        if (match && yflixProcessData2(argument2)
            === match && /\bSS\b/i.test(items) && /\bEP\b/i.test(items)) {
            return value3;
        }
    }
    return null;
}
async function yflixFetchData2(context, argument2) {
    const result = {
        "User-Agent": vidsrcwtfValue2
    };
    const requestOptions = {
        headers: result
    };
    const response = await context.proxiedFetcher("" + vidsrcwtfBaseUrl2 + argument2, requestOptions);
    const document = loadHtml(response);
    const dataId = document("div#movie-rating.rating").attr("data-id") || document("div.rating#movie-rating").attr("data-id");
    if (!dataId) {
        throw new ScraperError("yFlix: content id not found");
    }
    return dataId;
}
async function yflixExtractValue(context, key, key2, key3, key4) {
    const value = await vidsrcwtfFetchData(context, key);
    const result = {
        id: key,
        _: value
    };
    const requestOptions = {
        "User-Agent": vidsrcwtfValue2,
        Origin: vidsrcwtfBaseUrl2,
        Referer: key2,
        "X-Requested-With": "XMLHttpRequest",
        Accept: "application/json, text/javascript, */*; q=0.01"
    };
    const requestOptions2 = {
        query: result,
        headers: requestOptions
    };
    const response = await context.proxiedFetcher(vidsrcwtfValue + "/episodes/list", requestOptions2);
    const url = vidsrcwtfProcessData(response);
    const url2 = await vidsrcwtfFetchData2(context, url);
    const document = loadHtml(url);
    if (!key3 || !key4) {
        const numericValue = Object.keys(url2 ||
            {}).sort((left, right) => Number(left) - Number(right));
        const value10 = numericValue[0];
        const value11 = value10 ? url2[value10]?.eid : void 0;
        let type = typeof value11
            ===
                "string"
            ? value11 : void 0;
        if (type || (type = document("a[eid]").first().attr("eid")), !type) {
            const value12 = document.root().html() || "";
            const match = value12.match(/\s eid=\s*"([^"]+)"|\s eid=\s*'([^']+)'/);
            type = match ? match[1] || match[2] : void 0;
        }
        if (type || (type = key), !type) {
            throw new ScraperError("yFlix: episode id not found");
        }
        return type;
    }
    let temporaryValue3;
    const value13 = document("ul.episodes[data-season=\"" + key3 + '"]');
    if (value13.length && (temporaryValue3 = value13.find("a[eid][num=\"" + key4 + '"]').attr("eid"), temporaryValue3 || (temporaryValue3 = value13.find("a[eid]").filter((item, index) => document(index).attr("num") === String(key4)).attr("eid")), temporaryValue3 || (temporaryValue3 = value13.find("a[eid]").first().attr("eid"))), temporaryValue3 || (temporaryValue3 = document("a[eid]").first().attr("eid")), !temporaryValue3) {
        throw new ScraperError("yFlix: episode id not found");
    }
    return temporaryValue3;
}
async function yflixParseHtml3(context, key, key2) {
    const value = await vidsrcwtfFetchData(context, key);
    const result = {
        eid: key,
        _: value
    };
    const requestOptions = {
        "User-Agent": vidsrcwtfValue2,
        Origin: vidsrcwtfBaseUrl2,
        Referer: key2,
        "X-Requested-With": "XMLHttpRequest",
        Accept: "application/json, text/javascript, */*; q=0.01"
    };
    const requestOptions2 = {
        query: result,
        headers: requestOptions
    };
    const response = await context.proxiedFetcher(vidsrcwtfValue + "/links/list", requestOptions2);
    const url = vidsrcwtfProcessData(response);
    const url2 = await vidsrcwtfFetchData2(context, url);
    const document = loadHtml(url);
    const value8 = (url2?.default) || (url2?.DEFAULT) || (url2?.main);
    const value9 = value8 || url2;
    const numericValue = value9 ? value9[Object.keys(value9).sort((left, right) => Number(left) - Number(right))[0]]?.lid : void 0;
    if (typeof numericValue === "string" && numericValue) {
        return numericValue;
    }
    const value10 = document("[data-type=\"default\"]");
    const item = (value10.length ? value10 :
        document("body")).find("[data-lid]").first().attr("data-lid");
    if (!item) {
        throw new ScraperError("yFlix: server lid not found");
    }
    return item;
}
async function yflixFetchData3(context, argument2, argument3) {
    const value = await vidsrcwtfFetchData(context, argument2);
    const requestOptions = {
        id: argument2,
        _: value
    };
    const requestOptions2 = {
        "User-Agent": vidsrcwtfValue2,
        Origin: vidsrcwtfBaseUrl2,
        Referer: argument3,
        "X-Requested-With": "XMLHttpRequest",
        Accept: "application/json, text/javascript, */*; q=0.01"
    };
    const requestOptions3 = {
        query: requestOptions,
        headers: requestOptions2
    };
    const response = await context.proxiedFetcher(vidsrcwtfValue + "/links/view", requestOptions3);
    const type = typeof response === "string" ? response : response?.result;
    if (typeof type !== "string" || !type) {
        throw new ScraperError("yFlix: view result missing");
    }
    return type;
}
async function yflixResolveStream(context, argument2) {
    var temporaryValue3;
    const value = argument2.replace("/e/", "/media/");
    const requestOptions = {
        "User-Agent": vidsrcwtfValue2,
        Accept: "application/json"
    };
    const requestOptions2 = {
        headers: requestOptions
    };
    const response = await context.proxiedFetcher(value, requestOptions2);
    const data = typeof response == "string" ? JSON.parse(response) : response;
    const url = typeof (data?.result) === "string" ? data.result : typeof (data?.data?.result) === "string" ? data.data.result : null;
    if (!url) {
        throw new ScraperError("Rapid: missing encrypted media payload");
    }
    const url2 = await vidsrcwtfDecryptPayload2(context, url);
    const value6 = Array.isArray(url2?.sources) ? url2.sources : [];
    if (!value6.length || !((temporaryValue3 = value6[0]) != null && temporaryValue3.file)) {
        throw new ScraperError("Rapid: no sources");
    }
    const value7 = Array.isArray(url2?.tracks) ? url2.tracks : [];
    return { playlist: String(value6[0].file), tracks: value7 };
}
async function scrapeYflixMovie(context) {
    const value = await yflixFetchData(context, context.media.title);
    const value9 = yflixParseHtml(value, context.media.title, context.media.releaseYear);
    if (!value9) {
        throw new ScraperError("yFlix: movie not found");
    }
    const item = value9.find("a.poster").attr("href") || value9.find(".info .title").attr("href");
    if (!item) {
        throw new ScraperError("yFlix: movie href not found");
    }
    const url = "" + vidsrcwtfBaseUrl2 + item;
    const value10 = await yflixFetchData2(context, item);
    const extractedKey = await yflixExtractValue(context, value10, url);
    const value11 = await yflixParseHtml3(context, extractedKey, url);
    const url2 = await yflixFetchData3(context, value11, url);
    const url3 = await vidsrcwtfDecryptPayload(context, url2);
    const value12 = yflixProcessData(url3);
    const { playlist: playlist } = await yflixResolveStream(context, value12);
    const stream = {
        id: "primary",
        type: "hls",
        playlist: playlist,
        flags: ["cors-allowed"],
        captions: []
    };
    return {
        embeds: [],
        stream: [stream]
    };
}
async function scrapeYflixShow(context) {
    const value = await yflixFetchData(context, context.media.title);
    const value9 = yflixParseHtml2(value, context.media.title);
    if (!value9) {
        throw new ScraperError("yFlix: show not found");
    }
    const item = value9.find("a.poster").attr("href") || value9.find(".info .title").attr("href");
    if (!item) {
        throw new ScraperError("yFlix: show href not found");
    }
    const url = "" + vidsrcwtfBaseUrl2 + item;
    const value10 = await yflixFetchData2(context, item);
    const extractedKey = await yflixExtractValue(context, value10, url, context.media.season.number, context.media.episode.number);
    const value11 = await yflixParseHtml3(context, extractedKey, url);
    const url2 = await yflixFetchData3(context, value11, url);
    const url3 = await vidsrcwtfDecryptPayload(context, url2);
    const value12 = yflixProcessData(url3);
    const { playlist: playlist } = await yflixResolveStream(context, value12);
    const requestOptions = {
        Origin: "https://rapidairmax.site",
        Referer: "https://rapidairmax.site/"
    };
    return { embeds: [], stream: [{ id: "primary", type: "hls", playlist: buildProxiedHlsUrl(playlist, context.features, requestOptions), headers: { Origin: "https://rapidairmax.site", Referer: "https://rapidairmax.site/" }, flags: ["cors-allowed"], captions: [] }] };
}
const yflixProviderConfig = {
    id: "yflix",
    name: "Vespera \uD83C\uDF7F",
    disabled: true,
    rank: 6767,
    flags: ["cors-allowed"],
    scrapeMovie: scrapeYflixMovie,
    scrapeShow: scrapeYflixShow
};
const yflixProvider = createSourceProvider(yflixProviderConfig);
const zoechipBaseUrl = "https://zoechip.org";
function zoechipProcessData(input) {
    return input.toLowerCase().replace(/[^a-z0-9\s-]/g, "").replace(/\s+/g, "-").replace(/-+/g, "-").trim();
}
async function zoechipResolveStream(context, argument2) {
    const requestOptions = {
        Referer: zoechipBaseUrl,
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36"
    };
    const value = requestOptions;
    try {
        const requestOptions2 = {
            method: "HEAD",
            headers: value
        };
        const response = await context.proxiedFetcher.full(argument2, requestOptions2);
        const finalUrl2 = response.finalUrl;
        if (!finalUrl2) {
            return null;
        }
        const requestOptions3 = {
            headers: value
        };
        const response2 = await context.proxiedFetcher(finalUrl2, requestOptions3);
        const document = loadHtml(response2);
        const url = document("iframe").attr("src");
        if (!url) {
            throw new ScraperError("No iframe URL found");
        }
        const requestOptions4 = {
            headers: value
        };
        const response3 = await context.proxiedFetcher(url, requestOptions4);
        const match = response3.match(/eval\(function\(p,a,c,k,e,.*\)\)/i);
        if (!match) {
            throw new ScraperError("No packed JavaScript found");
        }
        const value4 = x2(match[0]);
        const match5 = value4.match(/file\s*:\s*"([^"]+)"/i);
        if (!match5) {
            throw new ScraperError("No file URL found in unpacked JavaScript");
        }
        return match5[1];
    }
    catch {
        throw new ScraperError("Failed to extract file URL from streaming server");
    }
}
async function scrapeZoechip(context) {
    const requestOptions = {
        Referer: zoechipBaseUrl,
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36"
    };
    const value = requestOptions;
    let temporaryValue;
    let temporaryValue4;
    try {
        if (context.media.type
            === "movie") {
            const url = zoechipProcessData(context.media.title);
            temporaryValue = zoechipBaseUrl + "/film/" + url + "-" + context.media.releaseYear;
        }
        else {
            const url3 = zoechipProcessData(context.media.title);
            temporaryValue = zoechipBaseUrl + "/episode/" + url3 + "-season-" + context.media.season.number + "-episode-" + context.media.episode.number;
        }
        context.progress(20);
        const requestOptions2 = {
            headers: value
        };
        const response = await context.proxiedFetcher(temporaryValue, requestOptions2);
        const document = loadHtml(response);
        if (temporaryValue4 = document("div#show_player_ajax").attr("movie-id"), !temporaryValue4) {
            ;
            {
                const dataId = document("[data-movie-id]").attr("data-movie-id") || document("[movie-id]").attr("movie-id") || document(".player-wrapper").attr("data-id");
                if (dataId) {
                    temporaryValue4 = dataId;
                }
                else {
                    throw new ScraperError("No content found for " + (context.media.type
                        === "movie"
                        ? "movie" : "episode"));
                }
            }
        }
        context.progress(40);
        const url4 = zoechipBaseUrl + "/wp-admin/admin-ajax.php";
        const requestOptions3 = { ...value };
        requestOptions3["X-Requested-With"] = "XMLHttpRequest";
        requestOptions3["Content-Type"] = "application/x-www-form-urlencoded; charset=UTF-8";
        requestOptions3.Referer = temporaryValue;
        const value9 = requestOptions3;
        const result = {
            action: "lazy_player",
            movieID: temporaryValue4
        };
        const queryParams = new URLSearchParams(result);
        const response2 = await context.proxiedFetcher(url4, { method: "POST", headers: value9, body: queryParams.toString() });
        const document3 = loadHtml(response2);
        const value10 = document3("ul.nav a:contains(Filemoon)").attr("data-server");
        if (!value10) {
            throw document3("ul.nav a").map((item, index) => ({ name: document3(index).text().trim(), url: document3(index).attr("data-server") })).get().length === 0 ? new ScraperError("No streaming servers found") : new ScraperError("Filemoon server not available");
        }
        context.progress(60);
        const value11 = await zoechipResolveStream(context, value10);
        if (!value11) {
            throw new ScraperError("Failed to extract file URL from streaming server");
        }
        context.progress(90);
        const stream = {
            id: "primary",
            type: "hls",
            playlist: value11,
            flags: ["cors-allowed"],
            captions: []
        };
        return {
            stream: [stream],
            embeds: []
        };
    }
    catch (temporaryValue5) {
        if (temporaryValue5 instanceof ScraperError) {
            throw temporaryValue5;
        }
        if (temporaryValue5 instanceof
            Error) {
            if (temporaryValue5.message.includes("fetch")) {
                throw new ScraperError("Failed to connect to ZoeChip");
            }
            if (temporaryValue5.message.includes("timeout")) {
                throw new ScraperError("Request timed out");
            }
        }
        throw new ScraperError("ZoeChip scraping failed: " + (temporaryValue5 instanceof Error ? temporaryValue5.message : "Unknown error"));
    }
}
const zoechipProviderConfig = {
    id: "zoechip",
    name: "ZoeChip \uD83E\uDDEC",
    rank: 171,
    disabled: true,
    flags: ["cors-allowed"],
    scrapeMovie: scrapeZoechip,
    scrapeShow: scrapeZoechip
};
const zoechipProvider = createSourceProvider(zoechipProviderConfig);
const zoechipBaseUrl2 = "https://flix.1anime.app";
function zoechipProcessData2(input, argument2, argument3) {
    const result = {};
    argument3 && (result.referer = argument3);
    return buildProxiedHlsUrl(argument2, input.features, result);
}
function zoechipDecodePayload(input, argument2) {
    if (argument2.includes("orbitproxy")) {
        try {
            const value = argument2.split(/orbitproxy\.[^/]+\//);
            if (value.length
                >=
                    2) {
                ;
                {
                    const parts = value[1].split(".m3u8")[0];
                    try {
                        const type = typeof window !== "undefined" ?
                            atob(parts)
                            : Buffer.from(parts, "base64").toString("utf-8");
                        const data = JSON.parse(type);
                        const value5 = data.u;
                        const value6 = data.r || "";
                        return zoechipProcessData2(input, value5, value6);
                    }
                    catch (temporaryValue) {
                        console.error("Error decoding/parsing orbitproxy data:", temporaryValue);
                    }
                }
            }
        }
        catch (url) {
            console.error("Error processing orbitproxy URL:", url);
        }
    }
    return argument2.includes("/m3u8-proxy?url=") ?
        rewriteProxyBaseUrl(argument2)
        : zoechipProcessData2(input, argument2);
}
function zoechipProcessData3(input) {
    return input.includes("onionflixer");
}
function zoechipNormalizeLanguage(input) {
    const results = [];
    if (input && Array.isArray(input)) {
        for (const item of input) {
            const value = item.url || item.file;
            const value3 = item.lang || item.label || "unknown";
            if (value) {
                results.push({ type: item.type || "vtt", url: value, language: MU[value3.toLowerCase()] || value3.toLowerCase() || "unknown" });
            }
        }
    }
    return results;
}
function zoechipMapCaptions(input, argument2) {
    if (!input) {
        throw new ScraperError("No response received");
    }
    if (input.error) {
        throw new ScraperError("" + input.error + (input.hint ? " - " + input.hint : ""));
    }
    if (Array.isArray(input)) {
        for (const item of input) {
            if (item.headers && item.sources && Array.isArray(item.sources)) {
                const match = item.sources.find(item => item.isM3U8);
                if (match && match.url) {
                    const value = zoechipDecodePayload(argument2, match.url);
                    const value10 = zoechipNormalizeLanguage(item.subtitles);
                    const stream = {
                        id: "primary",
                        type: "hls",
                        playlist: value,
                        flags: ["cors-allowed"],
                        captions: value10,
                        headers: item.headers
                    };
                    return {
                        stream: [stream]
                    };
                }
            }
            if (item.source && item.source.files && Array.isArray(item.source.files)) {
                const match2 = item.source.files.find(item => item.type === "hls" || item.file.includes(".m3u8"));
                if (match2 && match2.file) {
                    const value11 = zoechipDecodePayload(argument2, match2.file);
                    const value12 = zoechipNormalizeLanguage(item.source.subtitles);
                    const stream3 = {
                        id: "primary",
                        type: "hls",
                        playlist: value11,
                        flags: ["cors-allowed"],
                        captions: value12
                    };
                    return {
                        stream: [stream3]
                    };
                }
            }
        }
    }
    const sources2 = input.sources;
    if (sources2) {
        let url = null;
        for (const temporaryValue in sources2)
            if (Object.prototype.hasOwnProperty.call(sources2, temporaryValue)) {
                const url3 = sources2[temporaryValue];
                if (url3 && url3.length > 0) {
                    for (const url4 of url3)
                        if (url4.url && url4.isM3U8 && !zoechipProcessData3(url4.url)) {
                            url = url4;
                            break;
                        }
                    if (url) {
                        break;
                    }
                }
            }
        if (!url) {
            for (const temporaryValue4 in sources2)
                if (Object.prototype.hasOwnProperty.call(sources2, temporaryValue4)) {
                    const value13 = sources2[temporaryValue4];
                    if (value13 &&
                        value13.length
                            >
                                0) {
                        url = value13[0];
                        break;
                    }
                }
        }
        if (url && url.url) {
            const url5 = zoechipDecodePayload(argument2, url.url);
            const value14 = zoechipNormalizeLanguage(input.subtitles);
            argument2.progress(100);
            return { stream: [{ id: "primary", type: "hls", playlist: zoechipProcessData2(argument2, url5, argument2.referer), flags: ["cors-allowed"], captions: value14 }] };
        }
    }
    throw new ScraperError("No valid stream URL found in response");
}
const zoechipValue = {
    id: "autoembed",
    name: "Autoembed",
    rank: 165
};
const zoechipValue2 = {
    id: "vidsrcsu",
    name: "vidsrc.su",
    rank: 164,
    disabled: true
};
const zoechipValue3 = {
    id: "primebox",
    name: "Primebox",
    rank: 162,
    disabled: true
};
const zoechipValue4 = {
    id: "foxstream",
    name: "Foxstream",
    rank: 161,
    disabled: true
};
const zoechipValue5 = {
    id: "flixhq",
    name: "FlixHQ",
    rank: 166,
    disabled: true
};
const zoechipValue6 = {
    id: "goku",
    name: "Goku",
    rank: 163,
    disabled: true
};
function zoechipLookupEpisode(context) {
    return createEmbedProvider({ id: "oneserver-" + context.id, name: context.name, rank: context.rank, disabled: context.disabled, scrape: async function scrapeZoechipLookupEpisode(context) {
            const data = JSON.parse(context.url);
            const url = data.type === "movie" ? zoechipBaseUrl2 + "/movie/" + context.id + "/" + data.tmdbId : zoechipBaseUrl2 + "/tv/" + context.id + "/" + data.tmdbId + "/" + data.season + "/" + data.episode;
            try {
                const response = await context.fetcher(url);
                context.progress(50);
                return zoechipMapCaptions(response, context);
            }
            catch (error) {
                throw error instanceof ScraperError
                    ? error : new ScraperError("Failed to fetch from " + context.id + ": " + error);
            }
        } });
}
const zoechipValue7 = [zoechipValue, zoechipValue2, zoechipValue3, zoechipValue4, zoechipValue5, zoechipValue6];
const [zU, eL, xL, _L, cL, aL] = zoechipValue7.map(zoechipLookupEpisode);
const zoechipValue8 = {
    id: "hianime",
    name: "Hianime",
    rank: 269
};
const zoechipValue9 = {
    id: "animepahe",
    name: "Animepahe",
    rank: 268
};
const zoechipValue10 = {
    id: "anizone",
    name: "Anizone",
    rank: 267
};
function zoechipLookupEpisode2(context) {
    return createEmbedProvider({ id: "oneserver-" + context.id, name: context.name, rank: context.rank, scrape: async function scrapeZoechipLookupEpisode2(context) {
            const data = JSON.parse(context.url);
            const url = zoechipBaseUrl2 + "/anime/" + context.id + "/" + data.anilistId + (data.episode ? "/" + data.episode : "");
            try {
                {
                    const response = await context.fetcher(url);
                    return zoechipMapCaptions(response, context);
                }
            }
            catch (error) {
                throw error instanceof ScraperError ? error : new ScraperError("Failed to fetch from " + context.id + ": " + error);
            }
        } });
}
const zoechipValue11 = [zoechipValue8, zoechipValue9, zoechipValue10];
const [nL, dL, oL] = zoechipValue11.map(zoechipLookupEpisode2);
const zoechipValue12 = ["pahe", "zoro", "zaza", "meg", "bato"];
const zoechipBaseUrl3 = "https://backend.animetsu.to";
const zoechipValue13 = {
    referer: "https://animetsu.to/",
    origin: "https://backend.animetsu.to",
    accept: "application/json, text/plain, */*",
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
};
const zoechipValue14 = zoechipValue13;
function zoechipResolveStream2(serverName, argument2 = 100) {
    return createEmbedProvider({ id: "animetsu-" + serverName, name: "" + (serverName.charAt(0).toUpperCase() + serverName.slice(1)), rank: argument2, scrape: async function scrapeZoechipResolveStream2(context) {
            // Capture server from factory arg — scrape `context` shadows the outer name.
            const value2 = serverName;
            const data = JSON.parse(context.url);
            const { type: type2, anilistId: anilistId2, episode: episode2 } = data;
            if (type2 !== "movie" && type2 !== "show") {
                throw new ScraperError("Unsupported media type");
            }
            if (!anilistId2) {
                throw new ScraperError("AniList id missing");
            }
            const fetchTiddies = (subType) => context.proxiedFetcher("/api/anime/tiddies", {
                baseUrl: zoechipBaseUrl3,
                headers: zoechipValue14,
                query: {
                    server: value2,
                    id: String(anilistId2),
                    num: String(episode2 ?? 1),
                    subType,
                },
            });
            let response = await fetchTiddies("sub");
            let url = response?.sources?.[0];
            if (!(url != null && url.url)) {
                response = await fetchTiddies("dub");
                url = response?.sources?.[0];
            }
            if (!(url != null && url.url)) {
                throw new ScraperError("No source URL found");
            }
            const url3 = url.url;
            const value3 = url.type;
            const value4 = url.quality;
            let requestOptions = { ...zoechipValue14 };
            if (url3.includes("animetsu.cc")) {
                const { referer: referer2, origin: origin2, ...itemValue } = requestOptions;
                const requestOptions2 = { ...itemValue };
                requestOptions2.origin = "https://backend.animetsu.cc";
                requestOptions2.referer = "https://backend.animetsu.cc/";
                requestOptions = requestOptions2;
            }
            if (context.progress(100),
                value3 === "mp4") {
                let value5 = "unknown";
                if (value4) {
                    const match = value4.match(/(\d+)p?/);
                    if (match) {
                        (value5 =
                            parseInt(match[1], 10));
                    }
                }
                return { stream: [{ id: "primary", captions: [], qualities: { [value5]: { type: "mp4", url: buildProxiedHlsUrl(url3, context.features, requestOptions) } }, type: "file", headers: requestOptions, flags: ["cors-allowed"] }] };
            }
            return { stream: [{ id: "primary", type: "hls", playlist: buildProxiedHlsUrl(url3, context.features, requestOptions), headers: requestOptions, flags: ["cors-allowed"], captions: [] }] };
        } });
}
const closeloadValue = zoechipValue12.map((item, index) => zoechipResolveStream2(item, 300 - index));
const closeloadValue2 = {
    id: "autoembed-english",
    rank: 10
};
const closeloadValue3 = {
    id: "autoembed-hindi",
    rank: 9,
    disabled: true
};
const closeloadValue4 = {
    id: "autoembed-tamil",
    rank: 8,
    disabled: true
};
const closeloadValue5 = {
    id: "autoembed-telugu",
    rank: 7,
    disabled: true
};
const closeloadValue6 = {
    id: "autoembed-bengali",
    rank: 6,
    disabled: true
};
const closeloadValue7 = [closeloadValue2, closeloadValue3, closeloadValue4, closeloadValue5, closeloadValue6];
function closeloadMapCaptions(input) {
    return createEmbedProvider({ id: input.id, name: input.id.split("-").map(item => item[0].toUpperCase() + item.slice(1)).join(" "), disabled: input.disabled, rank: input.rank, scrape: async function scrapeCloseloadMapCaptions(context) {
            const stream = {
                id: "primary",
                type: "hls",
                playlist: context.url,
                flags: ["cors-allowed"],
                captions: []
            };
            return {
                stream: [stream]
            };
        } });
}
const [lL, hL, mL, yL, SL] = closeloadValue7.map(closeloadMapCaptions);
const closeloadBaseUrl = "https://cinemaos.live/api";
const closeloadValue8 = {
    id: "Zen",
    name: "Zeus",
    proxy: true
};
const closeloadValue9 = {
    id: "Noah",
    name: "Plato"
};
const closeloadValue10 = {
    id: "Ophim",
    name: "Blaze"
};
const closeloadValue11 = {
    id: "Hollywood",
    name: "Nova"
};
const closeloadValue12 = {
    id: "Atom",
    name: "Spark",
    proxy: true
};
const closeloadValue13 = {
    id: "Flash",
    name: "Giga"
};
const closeloadValue14 = {
    id: "Lightning",
    name: "Storm",
    proxy: true
};
const closeloadValue15 = {
    id: "Smash",
    name: "Mini",
    proxy: true
};
const closeloadValue16 = {
    id: "Mega",
    name: "Massive",
    proxy: true
};
const closeloadValue17 = {
    id: "Zoom",
    name: "Pulse"
};
const closeloadValue18 = {
    id: "Rizz",
    name: "Platinum",
    proxy: true
};
const closeloadValue19 = {
    id: "alpha",
    name: "Nexus"
};
const closeloadValue20 = {
    id: "bravo",
    name: "Universe"
};
const closeloadValue21 = {
    id: "charlie",
    name: "Galaxy"
};
const closeloadValue22 = {
    id: "delta",
    name: "Cosmos",
    proxy: true
};
const closeloadValue23 = {
    id: "echo",
    name: "Quantum"
};
const closeloadValue24 = {
    id: "foxtrot",
    name: "Flux"
};
const closeloadValue25 = {
    id: "golf",
    name: "Nebula"
};
const closeloadValue26 = {
    id: "Comet",
    name: "Nebula"
};
const closeloadValue27 = {
    id: "Pulsar",
    name: "Vortex"
};
const closeloadValue28 = {
    id: "MadPlay",
    name: "Prime",
    proxy: true
};
const closeloadValue29 = [closeloadValue8, closeloadValue9, closeloadValue10, closeloadValue11, closeloadValue12, closeloadValue13, closeloadValue14, closeloadValue15, closeloadValue16, closeloadValue17, closeloadValue18, closeloadValue19, closeloadValue20, closeloadValue21, closeloadValue22, closeloadValue23, closeloadValue24, closeloadValue25, closeloadValue26, closeloadValue27, closeloadValue28];
const closeloadValue30 = {
    Referer: "https://cinemaos.live/",
    Origin: "https://cinemaos.live",
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
};
const closeloadValue31 = closeloadValue30;
function closeloadExtractValue(text) {
    return new Uint8Array(text.match(/[\da-f]{2}/gi).map(item => parseInt(item, 16)));
}
async function closeloadDecryptPayload({ encrypted: a, cin: x, mao: e }) {
    const extractedKey = closeloadExtractValue("a1b2c3d4e4f6589012345678901477567890abcdef1234567890abcdef123456");
    const extractedKey2 = closeloadExtractValue(x);
    const extractedKey3 = closeloadExtractValue(e);
    const extractedKey4 = closeloadExtractValue(a);
    try {
        {
            const result = {
                name: "AES-GCM"
            };
            const value = await crypto.subtle.importKey("raw", extractedKey, result, false, ["decrypt"]);
            const value6 = new Uint8Array(extractedKey4.length
                +
                    extractedKey3.length);
            value6.set(extractedKey4);
            value6.set(extractedKey3, extractedKey4.length);
            const result2 = {
                name: "AES-GCM",
                iv: extractedKey2,
                tagLength: 128
            };
            const value7 = await crypto.subtle.decrypt(result2, value, value6);
            const value8 = new TextDecoder;
            const value9 = value8.decode(value7);
            return JSON.parse(value9);
        }
    }
    catch (temporaryValue) {
        throw console.error("Decryption failed:", temporaryValue), new ScraperError("Failed to decrypt response");
    }
}
function closeloadDecryptPayload2(context, language) {
    return createEmbedProvider({ id: "cinemaos-" + context.id, name: context.name, rank: language, scrape: async function scrapeCloseloadDecryptPayload2(context) {
            const data = JSON.parse(context.url);
            const { tmdbId: tmdbId2, type: type2 } = data;
            context.progress(20);
            const headers = {
                Referer: "https://cinemaos.live/",
                Origin: "https://cinemaos.live"
            };
            const headers3 = {
                headers: headers
            };
            const response = await context.proxiedFetcher(closeloadBaseUrl + "/auth", headers3);
            const data3 = (typeof response === "string" ? JSON.parse(response) : response).challenge;
            context.progress(40);
            const result = {
                challenge: data3
            };
            const response4 = await context.proxiedFetcher(closeloadBaseUrl + "/auth", { method: "POST", headers: { Referer: "https://cinemaos.live/", "Content-Type": "application/json", Origin: "https://cinemaos.live" }, body: JSON.stringify(result) });
            const data4 = (typeof response4 === "string" ? JSON.parse(response4) : response4).token;
            context.progress(60);
            const queryParams = new URLSearchParams({ type: type2 === "show" ? "tv" : "movie", tmdbId: tmdbId2, ...data.imdbId && { imdbId: data.imdbId }, ...data.season && { seasonId: data.season }, ...data.episode && { episodeId: data.episode }, ...data.title && { t: data.title }, ...data.releaseYear && { ry: data.releaseYear } });
            const url = closeloadBaseUrl + "/cinemaos?" + queryParams.toString();
            context.progress(80);
            const headers4 = {
                Referer: "https://cinemaos.live/",
                Authorization: "Bearer " + data4
            };
            const headers5 = {
                headers: headers4
            };
            const response5 = await context.proxiedFetcher(url, headers5);
            const data5 = typeof response5 === "string" ? JSON.parse(response5) : response5;
            if (!data5.data || !data5.data.encrypted) {
                throw new ScraperError("No encrypted data found");
            }
            const result5 = {
                encrypted: data5.data.encrypted,
                cin: data5.data.cin,
                mao: data5.data.mao
            };
            const value = await closeloadDecryptPayload(result5);
            if (!value || typeof value != "object" || !value.sources) {
                throw new ScraperError("No sources found after decryption");
            }
            context.progress(90);
            const url3 = value.sources[context.id];
            if (!url3) {
                throw new ScraperError("Couldn't find a stream for server: " + context.name);
            }
            const items = Array.isArray(value.captions) ? value.captions.map(item => ({ language: item.language || item.languageName || item.label || "", url: item.url, format: item.format || "", label: item.label || item.languageName || "" })) : [];
            if (url3.qualities &&
                typeof url3.qualities
                    ===
                        "object") {
                const captions = ["360", "480", "720", "1080", "4k", "unknown"];
                const url4 = Object.entries(url3.qualities);
                url4.sort(([X], [Z]) => {
                    const normalizedValue = captions.indexOf(X.toLowerCase());
                    const normalizedValue2 = captions.indexOf(Z.toLowerCase());
                    return normalizedValue === -1 &&
                        normalizedValue2 ===
                            -1 ? X.localeCompare(Z) : normalizedValue === -1 ? 1 : normalizedValue2 ===
                        -1
                        ? -1 :
                        normalizedValue - normalizedValue2;
                });
                const stream = {};
                for (const [itemValue, itemValue2] of url4) {
                    const url5 = itemValue2;
                    let normalizedValue = itemValue.toLowerCase();
                    normalizedValue ===
                        "4k"
                        && (normalizedValue = "4k");
                    normalizedValue === "unknown"
                        && (normalizedValue = "unknown");
                    const stream9 = {
                        type: "mp4",
                        url: url5.url
                    };
                    stream[normalizedValue] = stream9;
                }
                const stream10 = {
                    id: "primary",
                    type: "file",
                    flags: ["cors-allowed"],
                    qualities: stream,
                    captions: items
                };
                return {
                    stream: [stream10]
                };
            }
            if (url3.url && (url3.type === "hls" || url3.url.endsWith(".m3u8"))) {
                return { stream: [{ id: "primary", type: "hls", playlist: context.proxy ?
                                buildProxiedHlsUrl(url3.url, context.features, closeloadValue31)
                                : url3.url, flags: ["cors-allowed"], captions: items, headers: closeloadValue31 }] };
            }
            if (url3.url &&
                url3.type
                    === "mp4") {
                const stream11 = {
                    type: "mp4",
                    url: url3.url
                };
                const stream12 = {
                    unknown: stream11
                };
                const stream13 = {
                    id: "primary",
                    type: "file",
                    qualities: stream12,
                    flags: ["cors-allowed"],
                    captions: items
                };
                return {
                    stream: [stream13]
                };
            }
            throw new ScraperError("Couldn't parse stream for server: " + context);
        } });
}
const closeloadValue32 = closeloadValue29.map((item, index) => closeloadDecryptPayload2(item, 421 - index));
function closeloadDecodePayload(input) {
    const value = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/=";
    const normalizedValue = input.replace(/=+$/, "");
    let characterCode = "";
    if (normalizedValue.length % 4 === 1) {
        throw new Error("The string to be decoded is not correctly encoded.");
    }
    for (let value9 = 0, value10 = 0, value11 = 0; value11 <
        normalizedValue.length; value11++) {
        const value12 = normalizedValue.charAt(value11);
        const value13 = value.indexOf(value12);
        if (value13 ===
            -1) {
            continue;
        }
        value10 = value9 %
            4
            ?
                value10 *
                    64 + value13
            : value13;
        value9++
            %
                4
            && (characterCode += String.fromCharCode(255 &
                value10 >> (-2
                    * value9 &
                    6)));
    }
    return characterCode;
}
function closeloadDecodePayload2(input) {
    let value = input.join("");
    value = atob(value);
    value = value.replace(/[a-zA-Z]/g, function (argument1) {
        const characterCode = argument1.charCodeAt(0);
        const value = characterCode + 13;
        const value6 = argument1 <= "Z" ? 90 : 122;
        return String.fromCharCode(value <= value6 ? value : value - 26);
    });
    value = value.split("").reverse().join("");
    let characterCode = "";
    for (let characterCode2 = 0; characterCode2 < value.length; characterCode2++) {
        let characterCode3 = value.charCodeAt(characterCode2);
        characterCode3 =
            (characterCode3 - 399756995
                % (characterCode2 +
                    5) +
                256) %
                256;
        characterCode += String.fromCharCode(characterCode3);
    }
    return characterCode;
}
async function scrapeCloseload(context) {
    const parsedUrl = new URL(context.url).origin;
    const result = {
        referer: closeloadBaseUrl2
    };
    const requestOptions = {
        headers: result
    };
    const response = await context.proxiedFetcher(context.url, requestOptions);
    const document = loadHtml(response);
    const language = document("track").map((item, index) => {
        const value = document(index);
        const url = "" + parsedUrl + value.attr("src");
        const value8 = value.attr("label") ?? "";
        const language = normalizeLanguageCode(value8);
        const subtitleType = getSubtitleFileType(url);
        if (!language || !subtitleType) {
            return null;
        }
        return {
            id: url,
            language: language,
            hasCorsRestrictions: true,
            type: subtitleType,
            url: url
        };
    }).get().filter(item => item !== null);
    const value = document("script").filter((item, index3) => {
        var value;
        const value8 = document(index3);
        return (value8.attr("type")
            === "text/javascript"
            && ((value = value8.html()) == null ? void 0 : value.includes("p,a,c,k,e,d"))) ?? false;
    }).html();
    if (!value) {
        throw new Error("Couldn't find eval code");
    }
    const value7 = x2(value);
    let temporaryValue;
    const match = value7.match(/dc_\w+\(\[([^\]]+)\]\)/);
    if (match) {
        ;
        {
            const value8 = match[1];
            const match6 = value8.match(/"([^"]+)"/g);
            if (match6) {
                const items = match6.map(item => item.slice(1, -1));
                try {
                    const value9 = closeloadDecodePayload2(items);
                    if ((value9.startsWith("http://") || value9.startsWith("https://"))) {
                        (temporaryValue = value9);
                    }
                }
                catch {
                }
            }
        }
    }
    if (!temporaryValue) {
        const captions = [/var\s+(\w+)\s*=\s*"([^"]+)";/g, /(\w+)\s*=\s*"([^"]+)"/g, /"([A-Za-z0-9+/=]+)"/g];
        for (const item of captions) {
            const value10 = item.exec(value7);
            if (value10) {
                const value11 = value10[2] || value10[1];
                if (/^[A-Za-z0-9+/]*={0,2}$/.test(value11) &&
                    value11.length
                        >
                            10) {
                    temporaryValue = value11;
                    break;
                }
            }
        }
    }
    if (!temporaryValue) {
        throw new ScraperError("Unable to find source url");
    }
    let temporaryValue4;
    if (temporaryValue.startsWith("http://") || temporaryValue.startsWith("https://")) {
        temporaryValue4 = temporaryValue;
    }
    else {
        if (!/^[A-Za-z0-9+/]*={0,2}$/.test(temporaryValue)) {
            throw new ScraperError("Invalid base64 encoding found in source url");
        }
        let temporaryValue5;
        try {
            temporaryValue5 = atob(temporaryValue);
        }
        catch {
            try {
                temporaryValue5 =
                    closeloadDecodePayload(temporaryValue);
            }
            catch {
                throw new ScraperError("Failed to decode base64 source url: " + temporaryValue.substring(0, 50) + "...");
            }
        }
        const match7 = temporaryValue5.match(/(https?:\/\/[^\s"']+)/);
        if (match7) {
            temporaryValue4 = match7[1];
        }
        else if (temporaryValue5.startsWith("http://") || temporaryValue5.startsWith("https://")) {
            temporaryValue4 = temporaryValue5;
        }
        else {
            throw new ScraperError("Decoded string is not a valid URL: " + temporaryValue5.substring(0, 100) + "...");
        }
    }
    const stream = {
        id: "primary",
        type: "hls",
        playlist: temporaryValue4,
        captions: language,
        flags: ["ip-locked"],
        headers: {}
    };
    stream.headers.Referer = "https://closeload.top/";
    stream.headers.Origin = "https://closeload.top";
    return {
        stream: [stream]
    };
}
const closeloadBaseUrl2 = "https://ridomovies.tv/";
const closeloadEmbedProvider = createEmbedProvider({ id: "closeload", name: "CloseLoad", rank: 106, disabled: true, scrape: scrapeCloseload });
const madplayBaseValue = "a7f3e9d2c8b4a1f6e3d9c5b8a4f7e2d1";
const madplayBaseValue2 = {
    Accept: "application/json, text/plain, */*",
    Referer: "https://vidfast.lordflix.club/"
};
const madplayBaseValue3 = madplayBaseValue2;
function madplayBaseDecodePayload(input) {
    const value = input.replace(/-/g, "+").replace(/_/g, "/");
    const token = CryptoJS.enc.Base64.parse(value);
    const token5 = CryptoJS.lib.WordArray.create(token.words.slice(0, 4));
    const token6 = CryptoJS.lib.WordArray.create(token.words.slice(4));
    const token7 = CryptoJS.enc.Hex.parse(madplayBaseValue);
    const result = {
        ciphertext: token6
    };
    return CryptoJS.AES.decrypt(result, token7, { iv: token5, mode: CryptoJS.mode.CBC, padding: CryptoJS.pad.Pkcs7 }).toString(CryptoJS.enc.Utf8);
}
async function madplayBaseDecryptPayload(context) {
    var temporaryValue;
    if (!context.url) {
        throw new ScraperError("Flipper URL missing");
    }
    const requestOptions = {
        headers: madplayBaseValue3
    };
    const response = await context.proxiedFetcher(context.url, requestOptions);
    let temporaryValue3;
    try {
        const value = madplayBaseDecodePayload(response);
        temporaryValue3 = JSON.parse(value);
    }
    catch {
        throw new ScraperError("Failed to decrypt Flipper response");
    }
    if (!Array.isArray(temporaryValue3.sources) || temporaryValue3.sources.length === 0) {
        throw new ScraperError("No sources found");
    }
    const captions = ["4K", "1080p", "720p", "360p"];
    let url = null;
    for (const item of captions) {
        const match = temporaryValue3.sources.find(item => item.quality === item);
        if (match != null && match.url) {
            url = match;
            break;
        }
    }
    if (!(url != null && url.url)) {
        throw new ScraperError("No valid stream URL found");
    }
    const language = ((temporaryValue = temporaryValue3.subtitles) == null ? void 0 : temporaryValue.map(item => {
        if (!item.url) {
            return null;
        }
        const language = normalizeLanguageCode(item.lang || item.language || "");
        if (!language) {
            return null;
        }
        return {
            id: item.url,
            url: item.url,
            language: language,
            type: "vtt",
            hasCorsRestrictions: false
        };
    }).filter(item => item !== null)) || [];
    const value4 = deduplicateCaptionsByLanguage(language);
    return { stream: [{ id: "primary", type: "hls", playlist: buildProxiedHlsUrl(url.url, context.features, { Origin: "https://videasy.net", Referer: "https://videasy.net/" }), flags: ["cors-allowed"], captions: value4 }] };
}
function madplayBaseProcessData(input, argument2, argument3) {
    return createEmbedProvider({ id: "flipper-" + input, name: argument2, rank: argument3, scrape: async function scrapeMadplayBaseProcessData(context) {
            return madplayBaseDecryptPayload(context);
        } });
}
const madplayBaseValue4 = madplayBaseProcessData("neon", "Neon", 1270);
const madplayBaseValue5 = madplayBaseProcessData("sage", "Sage", 1269);
const madplayBaseValue6 = madplayBaseProcessData("cypher", "Cypher", 1268);
const madplayBaseValue7 = madplayBaseProcessData("yoru", "Yoru", 1267);
const madplayBaseValue8 = madplayBaseProcessData("reyna", "Reyna", 1266);
const madplayBaseValue9 = madplayBaseProcessData("omen", "Omen", 1265);
const madplayBaseValue10 = madplayBaseProcessData("breach", "Breach", 1264);
const madplayBaseValue11 = madplayBaseProcessData("vyse", "Vyse", 1263);
const madplayBaseValue12 = madplayBaseProcessData("killjoy", "Killjoy", 1262);
const madplayBaseValue13 = madplayBaseProcessData("harbor", "Harbor", 1261);
const madplayBaseValue14 = madplayBaseProcessData("chamber", "Chamber", 1260);
const madplayBaseValue15 = madplayBaseProcessData("fade", "Fade", 1259);
const madplayBaseValue16 = madplayBaseProcessData("gekko", "Gekko", 1258);
const madplayBaseValue17 = madplayBaseProcessData("kayo", "Kayo", 1257);
const madplayBaseValue18 = madplayBaseProcessData("raze", "Raze", 1256);
const madplayBaseValue19 = madplayBaseProcessData("phoenix", "Phoenix", 1255);
const madplayBaseValue20 = madplayBaseProcessData("astra", "Astra", 1254);
const madplayBaseValue21 = "madplay.site";
const madplayBaseValue22 = {
    referer: "https://madplay.site/",
    origin: "https://madplay.site",
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
};
async function scrapeMadplayBase(context) {
    const data = JSON.parse(context.url);
    const { type: type2, tmdbId: tmdbId2, season: season2, episode: episode2 } = data;
    let requestUrl = "https://" + madplayBaseValue21 + "/api/playsrc";
    if (type2 === "movie") {
        ;
        requestUrl += "?id=" + tmdbId2;
    }
    else {
        type2 === "show" && (requestUrl += "?id=" + tmdbId2 + "&season=" + season2 + "&episode=" + episode2);
    }
    const requestOptions = {
        headers: madplayBaseValue23
    };
    const response = await context.proxiedFetcher(requestUrl, requestOptions);
    if (console.log(response), !Array.isArray(response) || response.length === 0) {
        throw new ScraperError("No streams found");
    }
    const value = response[0];
    if (!value.file) {
        throw new ScraperError("No file URL found in stream");
    }
    context.progress(100);
    return { stream: [{ id: "primary", type: "hls", playlist: buildProxiedHlsUrl(value.file, context.features, madplayBaseValue23), headers: madplayBaseValue23, flags: ["cors-allowed"], captions: [] }] };
}
async function scrapeMadplayNsapi(context) {
    const data = JSON.parse(context.url);
    const { type: type2, tmdbId: tmdbId2, season: season2, episode: episode2 } = data;
    let requestUrl = "https://" + madplayBaseValue21 + "/api/nsapi/vid";
    type2 === "movie" ? requestUrl += "?id=" + tmdbId2 : type2 === "show" && (requestUrl += "?id=" + tmdbId2 + "&season=" + season2 + "&episode=" + episode2);
    const requestOptions = {
        headers: madplayBaseValue23
    };
    const response = await context.proxiedFetcher(requestUrl, requestOptions);
    if (console.log(response), !Array.isArray(response) || response.length === 0) {
        throw new ScraperError("No streams found");
    }
    const value = response[0];
    if (!value.url) {
        throw new ScraperError("No file URL found in stream");
    }
    context.progress(100);
    return { stream: [{ id: "primary", type: "hls", playlist: buildProxiedHlsUrl(value.url, context.features, value.headers || madplayBaseValue23), headers: value.headers || madplayBaseValue23, flags: ["cors-allowed"], captions: [] }] };
}
async function scrapeMadplayRoper(context) {
    const data = JSON.parse(context.url);
    const { type: type2, tmdbId: tmdbId2, season: season2, episode: episode2 } = data;
    let requestUrl = "https://" + madplayBaseValue21 + "/api/roper/";
    type2 === "movie" ? requestUrl += "?id=" + tmdbId2 + "&type=movie" : type2 === "show" && (requestUrl += "?id=" + tmdbId2 + "&season=" + season2 + "&episode=" + episode2 + "&type=series");
    const requestOptions = {
        headers: madplayBaseValue23
    };
    const response = await context.proxiedFetcher(requestUrl, requestOptions);
    if (console.log(response), !Array.isArray(response) || response.length === 0) {
        throw new ScraperError("No streams found");
    }
    const value = response[0];
    if (!value.url) {
        throw new ScraperError("No file URL found in stream");
    }
    context.progress(100);
    return { stream: [{ id: "primary", type: "hls", playlist: buildProxiedHlsUrl(value.url, context.features, value.headers || madplayBaseValue23), headers: value.headers || madplayBaseValue23, flags: ["cors-allowed"], captions: [] }] };
}
async function scrapeMadplayVidfast(context) {
    const data = JSON.parse(context.url);
    const { type: type2, tmdbId: tmdbId2, season: season2, episode: episode2 } = data;
    let requestUrl = "https://" + madplayBaseValue21 + "/api/nsapi/test?url=https://vidfast.pro/";
    type2 === "movie" ? requestUrl += "/movie/" + tmdbId2 : type2 === "show" && (requestUrl += "/tv/" + tmdbId2 + "/" + season2 + "/" + episode2);
    const requestOptions = {
        headers: madplayBaseValue23
    };
    const response = await context.proxiedFetcher(requestUrl, requestOptions);
    if (console.log(response), !Array.isArray(response) || response.length === 0) {
        throw new ScraperError("No streams found");
    }
    const value = response[0];
    if (!value.url) {
        throw new ScraperError("No file URL found in stream");
    }
    context.progress(100);
    return { stream: [{ id: "primary", type: "hls", playlist: buildProxiedHlsUrl(value.url, context.features, value.headers || madplayBaseValue23), headers: value.headers || madplayBaseValue23, flags: ["cors-allowed"], captions: [] }] };
}
const madplayBaseValue23 = madplayBaseValue22;
const madplayBaseEmbedProvider = createEmbedProvider({ id: "madplay-base", name: "Base", rank: 134, scrape: scrapeMadplayBase });
const madplayNsapiEmbedProvider = createEmbedProvider({ id: "madplay-nsapi", name: "Northstar", rank: 133, scrape: scrapeMadplayNsapi });
const madplayRoperEmbedProvider = createEmbedProvider({ id: "madplay-roper", name: "Roper", rank: 132, scrape: scrapeMadplayRoper });
const madplayVidfastEmbedProvider = createEmbedProvider({ id: "madplay-vidfast", name: "Vidfast", rank: 131, scrape: scrapeMadplayVidfast });
const myanimedubValue = {
    id: "mp4hydra-1",
    name: "MP4Hydra Server 1",
    rank: 36
};
const myanimedubValue2 = {
    id: "mp4hydra-2",
    name: "MP4Hydra Server 2",
    rank: 35,
    disabled: true
};
const myanimedubValue3 = [myanimedubValue, myanimedubValue2];
function myanimedubMapCaptions(input) {
    return createEmbedProvider({ id: input.id, name: input.name, disabled: true, rank: input.rank, scrape: async function scrapeMyanimedubMapCaptions(context) {
            const [itemValue, itemValue2] = context.url.split("|");
            const stream = {
                url: itemValue,
                type: "mp4"
            };
            return { stream: [{ id: "primary", type: "file", qualities: { [fsharetvMapQuality(itemValue2 || "")]: stream }, flags: ["cors-allowed"], captions: [] }] };
        } });
}
async function scrapeMyanimedub(context) {
    var temporaryValue4;
    var temporaryValue5;
    const response = await context.proxiedFetcher("https://myanime.aether.mom/api/stream?id=" + context.url + "&server=HD-2&type=dub");
    if (!((temporaryValue4 = response.results.streamingLink?.link) != null && temporaryValue4.file)) {
        throw new ScraperError("No watchable sources found");
    }
    const value = argument1 => {
        if (!argument1 || typeof argument1 != "object") {
            return null;
        }
        const numericValue = parseInt(argument1.start, 10);
        const numericValue2 = parseInt(argument1.end, 10);
        if (Number.isNaN(numericValue) || Number.isNaN(numericValue2) || numericValue <= 0 ||
            numericValue2 <=
                0 ||
            numericValue >= numericValue2) {
            return null;
        }
        return {
            start: numericValue,
            end: numericValue2
        };
    };
    const value4 = value(response.results.streamingLink.intro);
    const value5 = value(response.results.streamingLink.outro);
    return { stream: [{ id: "dub", type: "hls", playlist: buildProxiedHlsUrl(response.results.streamingLink.link.file, context.features, { Referer: "https://rapid-cloud.co/" }), headers: { Referer: "https://rapid-cloud.co/" }, flags: ["cors-allowed"], captions: ((temporaryValue5 = response.results.streamingLink.tracks) == null ? void 0 : temporaryValue5.map(item => {
                    const language = normalizeLanguageCode(item.label);
                    const subtitleType = getSubtitleFileType(item.file);
                    if (!language
                        ||
                            !subtitleType) {
                        return null;
                    }
                    return {
                        id: item.file,
                        url: item.file,
                        language: language,
                        type: subtitleType,
                        hasCorsRestrictions: true
                    };
                }).filter(item => item)) ?? [], intro: value4, outro: value5 }] };
}
async function scrapeMyanimesub(context) {
    var temporaryValue4;
    var temporaryValue5;
    const response = await context.proxiedFetcher("https://myanime.aether.mom/api/stream?id=" + context.url + "&server=HD-2&type=sub");
    if (!((temporaryValue4 = response.results.streamingLink?.link) != null && temporaryValue4.file)) {
        throw new ScraperError("No watchable sources found");
    }
    const value = argument1 => {
        if (!argument1 ||
            typeof argument1
                !== "object") {
            return null;
        }
        const numericValue = parseInt(argument1.start, 10);
        const numericValue2 = parseInt(argument1.end, 10);
        if (Number.isNaN(numericValue) || Number.isNaN(numericValue2) ||
            numericValue <=
                0 ||
            numericValue2 <=
                0 ||
            numericValue >= numericValue2) {
            return null;
        }
        return {
            start: numericValue,
            end: numericValue2
        };
    };
    const value4 = value(response.results.streamingLink.intro);
    const value5 = value(response.results.streamingLink.outro);
    const requestOptions = {
        Referer: "https://rapid-cloud.co/"
    };
    return { stream: [{ id: "sub", type: "hls", playlist: buildProxiedHlsUrl(response.results.streamingLink.link.file, context.features, requestOptions), headers: { Referer: "https://rapid-cloud.co/" }, flags: ["cors-allowed"], captions: ((temporaryValue5 = response.results.streamingLink.tracks) == null ? void 0 : temporaryValue5.map(item => {
                    const language = normalizeLanguageCode(item.label);
                    const subtitleType = getSubtitleFileType(item.file);
                    if (!language
                        ||
                            !subtitleType) {
                        return null;
                    }
                    return {
                        id: item.file,
                        url: item.file,
                        language: language,
                        type: subtitleType,
                        hasCorsRestrictions: true
                    };
                }).filter(item => item)) ?? [], intro: value4, outro: value5 }] };
}
const [xX, _X] = myanimedubValue3.map(myanimedubMapCaptions);
const myanimedubEmbedProvider = createEmbedProvider({ id: "myanimedub", name: "MyAnime (Dub)", rank: 205, scrape: scrapeMyanimedub });
const myanimesubEmbedProvider = createEmbedProvider({ id: "myanimesub", name: "MyAnime (Sub)", rank: 204, scrape: scrapeMyanimesub });
const ridooBaseUrl = "https://ridomovies.tv/";
const ridooValue = {
    referer: "https://ridoo.net/",
    origin: "https://ridoo.net"
};
async function scrapeRidoo(context) {
    const result = {
        referer: ridooBaseUrl
    };
    const requestOptions = {
        headers: result
    };
    const response = await context.proxiedFetcher(context.url, requestOptions);
    const value = /file:"([^"]+)"/g;
    const value3 = value.exec(response)?.[1];
    if (!value3) {
        throw new ScraperError("Unable to find source url");
    }
    const stream = {
        id: "primary",
        type: "hls",
        playlist: value3,
        headers: ridooValue2,
        captions: [],
        flags: ["cors-allowed"]
    };
    return {
        stream: [stream]
    };
}
const ridooValue2 = ridooValue;
const ridooEmbedProvider = createEmbedProvider({ id: "ridoo", name: "Ridoo", rank: 105, scrape: scrapeRidoo });
const streamvidValue = {
    id: "streamtape",
    name: "Streamtape",
    rank: 160
};
const streamvidValue2 = {
    id: "streamtape-latino",
    name: "Streamtape (Latino)",
    rank: 159
};
const streamvidValue3 = [streamvidValue, streamvidValue2];
function streamvidResolveStream(context) {
    return createEmbedProvider({ id: context.id, name: context.name, rank: context.rank, scrape: async function scrapeStreamvidResolveStream(context) {
            var value;
            const response = await context.proxiedFetcher(context.url, { headers: { Referer: context.url } });
            const match = response.match(/robotlink'\).innerHTML = (.*)'/);
            if (!match) {
                throw new Error("No match found");
            }
            const [itemValue, itemValue2] = ((value = match?.[1]) == null ? void 0 : value.split("+ ('")) ?? [];
            if (!itemValue || !itemValue2) {
                throw new Error("No match found");
            }
            const url = "https:" + (itemValue == null ? void 0 : itemValue.replace(/'/g, "").trim()) + (itemValue2 == null ? void 0 : itemValue2.substring(3).trim());
            const stream = {
                id: "primary",
                type: "file",
                flags: ["cors-allowed", "ip-locked"],
                captions: [],
                qualities: {},
                headers: {}
            };
            stream.qualities.unknown = {};
            stream.qualities.unknown.type = "mp4";
            stream.qualities.unknown.url = url;
            stream.headers.Referer = "https://streamtape.com";
            return {
                stream: [stream]
            };
        } });
}
async function scrapeStreamvid(context) {
    const response = await context.proxiedFetcher(context.url);
    const match = response.match(streamvidPatterns);
    if (!match) {
        throw new Error("streamvid packed not found");
    }
    const value = Ch.unpack(match[1]);
    const match5 = value.match(streamvidPatterns2);
    if (!match5) {
        throw new Error("streamvid link not found");
    }
    const stream = {
        type: "hls",
        id: "primary",
        playlist: match5[1],
        flags: ["cors-allowed"],
        captions: []
    };
    return {
        stream: [stream]
    };
}
const [oX, fX] = streamvidValue3.map(streamvidResolveStream);
const streamvidPatterns = /(eval\(function\(p,a,c,k,e,d\).*\)\)\))/;
const streamvidPatterns2 = /src:"(https:\/\/[^"]+)"/;
const streamvidEmbedProvider = createEmbedProvider({ id: "streamvid", name: "Streamvid", rank: 215, scrape: scrapeStreamvid });
const vidcloudValue = {
    id: "streamwish-japanese",
    name: "StreamWish (Japones Sub Espa\u00F1ol)",
    rank: 171
};
const vidcloudValue2 = {
    id: "streamwish-latino",
    name: "StreamWish (Latino)",
    rank: 170
};
const vidcloudValue3 = {
    id: "streamwish-spanish",
    name: "StreamWish (Castellano)",
    rank: 169
};
const vidcloudValue4 = {
    id: "streamwish-english",
    name: "StreamWish (English)",
    rank: 168
};
const vidcloudValue5 = [vidcloudValue, vidcloudValue2, vidcloudValue3, vidcloudValue4];
function vidcloudResolveStream(input) {
    return createEmbedProvider({ id: input.id, name: input.name, rank: input.rank, scrape: async function scrapeVidcloudResolveStream(context) {
            const url = encodeURIComponent(context.url);
            const requestUrl = "https://ws-m3u8.moonpic.qzz.io/m3u8/" + url;
            const result = {
                Accept: "application/json"
            };
            const headers = {
                headers: result
            };
            const response = await fetch(requestUrl, headers);
            const data = await response.json();
            const value = data.m3u8;
            if (!value) {
                throw new ScraperError("No video URL found");
            }
            const stream = {
                id: "primary",
                type: "hls",
                playlist: value,
                flags: ["cors-allowed"],
                captions: []
            };
            return {
                stream: [stream]
            };
        } });
}
const [lX, hX, mX, yX] = vidcloudValue5.map(vidcloudResolveStream);
const vidcloudBaseUrl = "https://streameeeeee.site";
const vidcloudPatterns = [/<div data-dpi="([^"]+)" style="display:none">/, /<meta name="_gg_fb" content="([^"]+)">/, /<!-- _is_th:([^ ]+) -->/, /window\._xy_ws = "([^"]+)"/, /nonce="([^"]+)"/, /window\._lk_db = {x: "([^"]+)", y: "([^"]+)", z: "([^"]+)"}/];
function vidcloudExtractValue(text) {
    for (const item of vidcloudPatterns) {
        const match = text.match(item);
        if (match) {
            return match.length
                ===
                    4
                ? "" + match[1] + match[2] + match[3] : match[1];
        }
    }
    return null;
}
async function scrapeVidcloud(context) {
    const response = await context.proxiedFetcher(context.url, { headers: { Referer: context.url } });
    const document = loadHtml(response);
    const dataId = document("#vidcloud-player").attr("data-id");
    if (!dataId) {
        throw new ScraperError("Could not find data-id");
    }
    const extractedKey = vidcloudExtractValue(response);
    if (!extractedKey) {
        throw new ScraperError("Could not find k-value");
    }
    const sourcesUrl = vidcloudBaseUrl + "/embed-1/v3/e-1/getSources?id=" + dataId + "&_k=" + extractedKey;
    const sourcesResponse = await context.proxiedFetcher(sourcesUrl, { headers: { "X-Requested-With": "XMLHttpRequest", Referer: context.url } });
    if (!sourcesResponse.sources) {
        throw new ScraperError("No sources found");
    }
    const captions = [];
    if (sourcesResponse.tracks) {
        for (const track of sourcesResponse.tracks) {
            const language = normalizeLanguageCode(track.label);
            const subtitleType = getSubtitleFileType(track.file);
            if (!language || !subtitleType) {
                continue;
            }
            const caption = {
                id: track.file,
                url: track.file,
                language: language,
                type: subtitleType,
                hasCorsRestrictions: false
            };
            captions.push(caption);
        }
    }
    const requestOptions = {
        Referer: "https://streameeeeee.site/"
    };
    const value = requestOptions;
    const playlistUrl = buildProxiedHlsUrl(sourcesResponse.sources[0].file, context.features, value);
    const stream = {
        id: "primary",
        playlist: playlistUrl,
        type: "hls",
        flags: ["cors-allowed"],
        captions: captions,
        headers: value
    };
    return {
        stream: [stream]
    };
}
const vidcloudEmbedProvider = createEmbedProvider({ id: "vidcloud", name: "VidCloud", rank: 200, scrape: scrapeVidcloud });
function vidcloudProcessData(input) {
    let temporaryValue;
    try {
        temporaryValue = JSON.parse(input);
    }
    catch {
        throw new ScraperError("Invalid VidFast embed payload");
    }
    if (typeof temporaryValue.url
        !== "string"
        ||
            temporaryValue.url.length
                ===
                    0) {
        throw new ScraperError("VidFast embed payload is incomplete");
    }
    return temporaryValue;
}
function vidrockCometNormalizeLanguage(input) {
    if (!Array.isArray(input) || input.length === 0) {
        return [];
    }
    const items = input.filter(item => item && typeof item.url == "string" && typeof item.language == "string").map(item => ({ id: item.url, url: item.url, language: item.language, type: item.type === "vtt" ? "vtt" : "srt", hasCorsRestrictions: false }));
    return deduplicateCaptionsByLanguage(items);
}
async function vidrockCometMapCaptions(input) {
    if (!input.url) {
        throw new ScraperError("VidFast url missing");
    }
    const value = vidcloudProcessData(input.url);
    const value5 = value.noReferrer ? void 0 : value.headers ?? void 0;
    const value6 = vidrockCometNormalizeLanguage(value.captions);
    const playlistUrl = buildProxiedHlsUrl(value.url, input.features, value5 ?? {});
    const stream = {
        id: "primary",
        type: "hls",
        playlist: playlistUrl,
        headers: value5,
        flags: ["cors-allowed"],
        captions: value6
    };
    const value7 = stream;
    return {
        stream: [value7]
    };
}
const vidrockCometValue = {
    slug: "mega",
    displayName: "VidFast Mega",
    rank: 1178
};
const vidrockCometValue2 = {
    slug: "vedge",
    displayName: "VidFast vEdge",
    rank: 1177
};
const vidrockCometValue3 = {
    slug: "vfast",
    displayName: "VidFast vFast (4K)",
    rank: 1176
};
const vidrockCometValue4 = {
    slug: "beta",
    displayName: "VidFast Beta",
    rank: 1175
};
const vidrockCometValue5 = {
    slug: "charlie",
    displayName: "VidFast Charlie",
    rank: 1174
};
const vidrockCometValue6 = {
    slug: "cobra",
    displayName: "VidFast Cobra",
    rank: 1173
};
const vidrockCometValue7 = {
    slug: "max",
    displayName: "VidFast Max",
    rank: 1172
};
const vidrockCometValue8 = {
    slug: "vodka",
    displayName: "VidFast Vodka",
    rank: 1171
};
const vidrockCometValue9 = [vidrockCometValue, vidrockCometValue2, vidrockCometValue3, vidrockCometValue4, vidrockCometValue5, vidrockCometValue6, vidrockCometValue7, vidrockCometValue8];
const vidrockCometValue10 = vidrockCometValue9.map(item => createEmbedProvider({ id: "vidfast-" + item.slug, name: item.displayName, rank: item.rank, scrape: async function scrapeVidrockCometValue10(context) {
        return { oyzdD: function (t, r) {
                return t(r);
            } }.oyzdD(vidrockCometMapCaptions, context);
    } }));
const vidrockCometValue11 = ["alfa", "bravo", "charlie", "delta", "echo", "foxtrot", "golf", "hotel", "india", "juliett"];
const vidrockCometValue12 = "api.vidify.top";
const vidrockCometBaseUrl = "https://player.vidify.top/";
let vidrockCometValue13 = null;
let vidrockCometValue14 = 0;
async function vidrockCometExtractValue(context) {
    const timestamp = Date.now();
    if (vidrockCometValue13 && timestamp - vidrockCometValue14 < 3600000) {
        return vidrockCometValue13;
    }
    const response = await context.proxiedFetcher(vidrockCometBaseUrl, { headers: { Referer: vidrockCometBaseUrl } });
    const value = /\/assets\/index-([a-zA-Z0-9-]+)\.js/;
    const match = response.match(value);
    if (!match) {
        throw new Error("Could not find the JS file URL in the player page");
    }
    const parsedUrl = new URL(match[0], vidrockCometBaseUrl).href;
    const requestOptions = {
        Referer: vidrockCometBaseUrl
    };
    const requestOptions2 = {
        headers: requestOptions
    };
    const response2 = await context.proxiedFetcher(parsedUrl, requestOptions2);
    const value3 = /Authorization:"Bearer\s*([^"]+)"/;
    const match5 = response2.match(value3);
    if (!match5 || !match5[1]) {
        throw new Error("Could not extract the authorization header from the JS file");
    }
    vidrockCometValue13 = "Bearer " + match5[1];
    vidrockCometValue14 = timestamp;
    return vidrockCometValue13;
}
function vidrockCometResolveStream(context, key = 100) {
    const value = vidrockCometValue11.indexOf(context) + 1;
    return createEmbedProvider({ id: "vidify-" + context, name: "" + (context.charAt(0).toUpperCase() + context.slice(1)), rank: key, scrape: async function scrapeVidrockCometResolveStream(context) {
            const result = { rtzOK: ".mp4", ezKhC: "mp4", ePomr: function (argument1, argument2) {
                    return argument1(argument2);
                } };
            const data = JSON.parse(context.url);
            const { type: type2, tmdbId: tmdbId2, season: season2, episode: episode2 } = data;
            let requestUrl = "https://" + vidrockCometValue12 + "/";
            if (type2 === "movie") {
                requestUrl += "/movie/" + tmdbId2 + "?sr=" + value;
            }
            else if (type2 ===
                "show") {
                requestUrl += "/tv/" + tmdbId2 + "/season/" + season2 + "/episode/" + episode2 + "?sr=" + value;
            }
            else {
                throw new ScraperError("Unsupported media type");
            }
            const value = await vidrockCometExtractValue(context);
            const requestOptions = {
                referer: "https://player.vidify.top/",
                origin: "https://player.vidify.top",
                Authorization: value,
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
            };
            const value3 = requestOptions;
            const headers = {
                headers: value3
            };
            const response = await context.proxiedFetcher(requestUrl, headers);
            console.log(response);
            const url = response.m3u8 ?? response.url;
            if (Array.isArray(response.result) &&
                response.result.length
                    >
                        0) {
                const stream = {};
                if (response.result.forEach(item => { item.url.includes(result.rtzOK) && (stream[item.resolution + "p"] = { type: result.ezKhC, url: result.ePomr(decodeURIComponent, item.url) }); }), Object.keys(stream).length === 0) {
                    throw new ScraperError("No MP4 streams found");
                }
                console.log("Found MP4 streams: ", stream);
                const stream5 = {
                    id: "primary",
                    type: "file",
                    qualities: stream,
                    flags: ["cors-allowed"],
                    captions: [],
                    headers: {}
                };
                stream5.headers.Host = "proxy-worker.himanshu464121.workers.dev";
                return {
                    stream: [stream5]
                };
            }
            if (!url) {
                throw new ScraperError("No playlist URL found");
            }
            const result8 = { ...value3 };
            const url3 = result8;
            let url4;
            url.includes("proxyv1.vidify.top") ? (console.log("Found stream (proxyv1): ", url, url3), url3.Host = "proxyv1.vidify.top", url4 =
                decodeURIComponent(url)) : url.includes("proxyv2.vidify.top") ? (console.log("Found stream (proxyv2): ", url, url3), url3.Host = "proxyv2.vidify.top", url4 =
                decodeURIComponent(url)) : (console.log("Found normal stream: ", url), url4 =
                buildProxiedHlsUrl(decodeURIComponent(url), context.features, url3));
            context.progress(100);
            const stream6 = {
                id: "primary",
                type: "hls",
                playlist: url4,
                headers: url3,
                flags: ["cors-allowed"],
                captions: []
            };
            return {
                stream: [stream6]
            };
        } });
}
const vidrockCometValue15 = vidrockCometValue11.map((item, index) => vidrockCometResolveStream(item, 230 - index));
const vidrockCometValue16 = {
    Origin: "https://vidrock.net",
    Referer: "https://vidrock.net/"
};
const vidrockCometValue17 = vidrockCometValue16;
const vidrockCometValue18 = {
    id: "vidrock-comet",
    name: "Comet",
    rank: 39
};
async function scrapeVidrockPulsar(context) {
    if (context.url.includes(".mp4")) {
        const stream = {
            type: "mp4",
            url: context.url
        };
        const result = {
            unknown: stream
        };
        const requestOptions = {
            id: "primary",
            type: "file",
            qualities: result,
            headers: vidrockCometValue17,
            flags: [],
            captions: []
        };
        return {
            stream: [requestOptions]
        };
    }
    return { stream: [{ id: "primary", type: "hls", playlist: buildProxiedHlsUrl(context.url, context.features, vidrockCometValue17), flags: ["cors-allowed"], captions: [], headers: vidrockCometValue17 }] };
}
async function scrapeVidrockNova(context) {
    return { stream: [{ id: "primary", type: "hls", playlist: buildProxiedHlsUrl(context.url, context.features, vidrockCometValue17), flags: ["cors-allowed"], captions: [], headers: vidrockCometValue17 }] };
}
const vidrockCometEmbedProvider = createEmbedProvider(vidrockCometValue18);
const vidrockPulsarEmbedProvider = createEmbedProvider({ id: "vidrock-pulsar", name: "Pulsar", rank: 38, scrape: scrapeVidrockPulsar });
const vidrockNovaEmbedProvider = createEmbedProvider({ id: "vidrock-nova", name: "Nova", rank: 37, scrape: scrapeVidrockNova });
const vidstrBaseUrl = "https://videostr.net";
const vidstrPatterns = [/<div data-dpi="([^"]+)" style="display:none">/, /<meta name="_gg_fb" content="([^"]+)">/, /<!-- _is_th:([^ ]+) -->/, /window\._xy_ws = "([^"]+)"/, /nonce="([^"]+)"/, /window\._lk_db = {x: "([^"]+)", y: "([^"]+)", z: "([^"]+)"}/];
function vidstrExtractValue(text) {
    for (const item of vidstrPatterns) {
        const match = text.match(item);
        if (match) {
            return match.length
                ===
                    4
                ? "" + match[1] + match[2] + match[3] : match[1];
        }
    }
    return null;
}
async function scrapeVidstr(context) {
    const response = await context.proxiedFetcher(context.url, { headers: { Referer: context.url } });
    const document = loadHtml(response);
    const dataId = document("#megacloud-player").attr("data-id");
    if (!dataId) {
        throw new ScraperError("Could not find data-id");
    }
    const extractedKey = vidstrExtractValue(response);
    if (!extractedKey) {
        throw new ScraperError("Could not find k-value");
    }
    const sourcesUrl = vidstrBaseUrl + "/embed-1/v3/e-1/getSources?id=" + dataId + "&_k=" + extractedKey;
    const sourcesResponse = await context.proxiedFetcher(sourcesUrl, { headers: { "X-Requested-With": "XMLHttpRequest", Referer: context.url } });
    if (!sourcesResponse.sources) {
        throw new ScraperError("No sources found");
    }
    const captions = [];
    if (sourcesResponse.tracks) {
        for (const track of sourcesResponse.tracks) {
            const language = normalizeLanguageCode(track.label);
            const subtitleType = getSubtitleFileType(track.file);
            if (!language
                ||
                    !subtitleType) {
                continue;
            }
            const caption = {
                id: track.file,
                url: track.file,
                language: language,
                type: subtitleType,
                hasCorsRestrictions: false
            };
            captions.push(caption);
        }
    }
    const requestOptions = {
        Referer: "https://videostr.net/"
    };
    const value = requestOptions;
    const playlistUrl = buildProxiedHlsUrl(sourcesResponse.sources[0].file, context.features, value);
    const stream = {
        id: "primary",
        playlist: playlistUrl,
        type: "hls",
        flags: ["cors-allowed"],
        captions: captions,
        headers: value
    };
    return {
        stream: [stream]
    };
}
async function scrapeVidzeeServer1(context) {
    var temporaryValue;
    const data = JSON.parse(context.url);
    const result = {
        id: data.tmdbId,
        sr: "1"
    };
    const queryParams = new URLSearchParams(result);
    if (data.type === "show") {
        (queryParams.append("ss", data.season.toString()), queryParams.append("ep", data.episode.toString()));
    }
    const response = await context.proxiedFetcher(vidzeeServer1BaseUrl + "?" + queryParams.toString());
    if (!response) {
        throw new ScraperError("No response received");
    }
    if (!response.url || !Array.isArray(response.url) ||
        response.url.length
            ===
                0) {
        throw new ScraperError("No stream URL found in response");
    }
    const value = response.url[0];
    const link2 = value.link;
    const url = response.headers || {};
    if (url.Referer && url.Referer.includes("vidzee")) {
        (url.Origin = "https://player.vidzee.wtf");
    }
    const language = ((temporaryValue = response.tracks) == null ? void 0 : temporaryValue.map((item, index) => {
        return { id: index, type: "vtt", url: item.url, language: normalizeLanguageCode(item.lang) || "unknown" };
    })) || [];
    context.progress(90);
    const playlistUrl = Object.keys(url).length
        >
            0
        ?
            buildProxiedHlsUrl(link2, context.features, url)
        : link2;
    const stream = {
        type: "hls",
        id: "primary",
        playlist: playlistUrl,
        flags: ["cors-allowed"],
        captions: language,
        headers: url
    };
    return {
        stream: [stream]
    };
}
async function scrapeVidzeeServer2(context) {
    var temporaryValue;
    const data = JSON.parse(context.url);
    const result = {
        id: data.tmdbId,
        sr: "2"
    };
    const queryParams = new URLSearchParams(result);
    if (data.type === "show") {
        (queryParams.append("ss", data.season.toString()), queryParams.append("ep", data.episode.toString()));
    }
    const response = await context.proxiedFetcher(vidzeeServer1BaseUrl + "?" + queryParams.toString());
    if (!response) {
        throw new ScraperError("No response received");
    }
    if (!response.url || !Array.isArray(response.url) ||
        response.url.length
            ===
                0) {
        throw new ScraperError("No stream URL found in response");
    }
    const value = response.url[0];
    const link2 = value.link;
    const url = response.headers || {};
    if (url.Referer && url.Referer.includes("vidzee")) {
        (url.Origin = "https://player.vidzee.wtf/");
    }
    const language = ((temporaryValue = response.tracks) == null ? void 0 : temporaryValue.map((item, index) => {
        return { id: index, type: "vtt", url: item.url, language: normalizeLanguageCode(item.lang)
                || "unknown" };
    })) || [];
    context.progress(90);
    const playlistUrl = Object.keys(url).length
        >
            0
        ?
            buildProxiedHlsUrl(link2, context.features, url)
        : link2;
    const stream = {
        type: "hls",
        id: "primary",
        playlist: playlistUrl,
        flags: ["cors-allowed"],
        captions: language,
        headers: url
    };
    return {
        stream: [stream]
    };
}
async function scrapeViper(context) {
    const requestOptions = {
        Accept: "application/json",
        Referer: "https://embed.su/"
    };
    const requestOptions2 = {
        headers: requestOptions
    };
    const response = await context.proxiedFetcher.full(context.url, requestOptions2);
    if (!response.body.source) {
        throw new ScraperError("No source found");
    }
    const value = response.body.source.replace(/^.*\/viper\//, "https://");
    const result = {
        referer: "https://megacloud.store/",
        origin: "https://megacloud.store"
    };
    const url = result;
    return { stream: [{ type: "hls", id: "primary", playlist: buildProxiedHlsUrl(value, context.features, url), headers: url, flags: ["cors-allowed"], captions: [] }] };
}
const vidstrEmbedProvider = createEmbedProvider({ id: "vidstr", name: "VidStr", rank: 199, scrape: scrapeVidstr });
const vidzeeServer1BaseUrl = "https://player.vidzee.wtf/api/server";
const vidzeeServer1EmbedProvider = createEmbedProvider({ id: "vidzee-server1", name: "Server 1", rank: 34, scrape: scrapeVidzeeServer1 });
const vidzeeServer2EmbedProvider = createEmbedProvider({ id: "vidzee-server2", name: "Server 2", rank: 33, scrape: scrapeVidzeeServer2 });
const viperEmbedProvider = createEmbedProvider({ id: "viper", name: "Viper", rank: 182, disabled: true, scrape: scrapeViper });
async function warezcdnembedhlsResolveStream(context, argument2) {
    const response = await context.proxiedFetcher("https://cloud.mail.ru/public/uaRH/2PYWcJRpH");
    const value = /"videowl_view":\{"count":"(\d+)","url":"([^"]+)"\}/g;
    const value3 = value.exec(response)?.[2];
    if (!value3) {
        throw new ScraperError("Failed to get videoOwlUrl");
    }
    const result = {
        double_encode: "1"
    };
    return value3 + "/0p/" +
        btoa(argument2) + ".m3u8?" + new URLSearchParams(result);
}
async function scrapeWarezcdnembedhls(context) {
    const value = await lookupWarezcdnFileId(context);
    if (!value) {
        throw new ScraperError("can't get file id");
    }
    const value3 = await warezcdnembedhlsResolveStream(context, value);
    const stream = {
        id: "primary",
        type: "hls",
        flags: ["ip-locked"],
        captions: [],
        playlist: value3
    };
    return {
        stream: [stream]
    };
}
async function scrapeWarezplayer(context) {
    const parsedUrl = new URL(context.url);
    const value = parsedUrl.pathname.split("/")[2];
    const response = await context.proxiedFetcher("/player/index.php", { baseUrl: parsedUrl.origin, query: { data: value, do: "getVideo" }, method: "POST", body: new URLSearchParams({ hash: value }), headers: { "X-Requested-With": "XMLHttpRequest" } });
    const data = JSON.parse(response);
    if (!data.videoSource) {
        throw new Error("Playlist not found");
    }
    const stream = {
        id: "primary",
        type: "hls",
        flags: [],
        captions: [],
        playlist: data.videoSource,
        headers: {}
    };
    stream.headers.Accept = "*/*";
    return {
        stream: [stream]
    };
}
const warezcdnembedhlsEmbedProvider = createEmbedProvider({ id: "warezcdnembedhls", name: "WarezCDN HLS", disabled: true, rank: 83, scrape: scrapeWarezcdnembedhls });
const warezplayerEmbedProvider = createEmbedProvider({ id: "warezplayer", name: "warezPLAYER", disabled: true, rank: 85, scrape: scrapeWarezplayer });
const xprimeRageValue = {
    id: "webtor-1080",
    rank: 80
};
const xprimeRageValue2 = {
    id: "webtor-4k",
    rank: 79
};
const xprimeRageValue3 = {
    id: "webtor-720",
    rank: 78
};
const xprimeRageValue4 = {
    id: "webtor-480",
    rank: 77
};
const xprimeRageValue5 = [xprimeRageValue, xprimeRageValue2, xprimeRageValue3, xprimeRageValue4];
function xprimeRageMapCaptions(input) {
    return createEmbedProvider({ id: input.id, name: "Webtor " + input.id.split("-")[1].toUpperCase(), rank: input.rank, scrape: async function scrapeXprimeRageMapCaptions(context) {
            const stream = {
                id: "primary",
                type: "hls",
                playlist: context.url,
                flags: ["cors-allowed"],
                captions: []
            };
            return {
                stream: [stream]
            };
        } });
}
const [BX, KX, DX, MX] = xprimeRageValue5.map(xprimeRageMapCaptions);
async function xprimeRageResolveStream(context) {
    var temporaryValue5;
    const response = await context.fetcher(context.url);
    if (!((temporaryValue5 = response.playlist?.[0]?.sources) != null && temporaryValue5[0])) {
        throw new ScraperError("No streams found in XPass response");
    }
    const playlistUrl = response.playlist[0].sources[0];
    if (!playlistUrl.file) {
        throw new ScraperError("No file URL in XPass source");
    }
    if (playlistUrl.type
        === "mp4") {
        const stream = {
            id: "primary",
            type: "file",
            qualities: {},
            flags: ["cors-allowed"],
            captions: []
        };
        stream.qualities.unknown = {};
        stream.qualities.unknown.type = "mp4";
        stream.qualities.unknown.url = playlistUrl.file;
        return {
            stream: [stream]
        };
    }
    const stream3 = {
        id: "primary",
        type: "hls",
        playlist: playlistUrl.file,
        flags: ["cors-allowed"],
        captions: []
    };
    return {
        stream: [stream3]
    };
}
function xprimeRageProcessData(input, argument2, argument3) {
    return createEmbedProvider({ id: "xpass-" + input, name: argument2, rank: argument3, scrape: async function scrapeXprimeRageProcessData(context) {
            return xprimeRageResolveStream(context);
        } });
}
function xprimeRageProcessData2() {
    try {
        require("react-native");
        return true;
    }
    catch {
        return false;
    }
}
const xprimeRageValue6 = xprimeRageProcessData("sfy", "Silver", 1500);
const xprimeRageValue7 = xprimeRageProcessData("sfy-1", "Silver 1", 1499);
const xprimeRageValue8 = xprimeRageProcessData("sfy-2", "Silver 2", 1498);
const xprimeRageValue9 = xprimeRageProcessData("big", "Bronze", 1497);
const xprimeRageValue10 = xprimeRageProcessData("big-1", "Bronze 1", 1496);
const xprimeRageValue11 = xprimeRageProcessData("big-2", "Bronze 2", 1495);
const xprimeRageValue12 = xprimeRageProcessData("mov", "Gold", 1494);
const xprimeRageValue13 = xprimeRageProcessData("mov-1", "Gold 1", 1493);
const xprimeRageValue14 = xprimeRageProcessData("mov-2", "Gold 2", 1492);
const xprimeRageValue15 = xprimeRageProcessData("meg", "Diamond", 1491);
const xprimeRageValue16 = xprimeRageProcessData("meg-1", "Diamond 1", 1490);
const xprimeRageValue17 = xprimeRageProcessData("meg-2", "Diamond 2", 1489);
const xprimeRageValue18 = xprimeRageProcessData("voe", "Platinum", 1488);
const xprimeRageValue19 = xprimeRageProcessData("voe-1", "Platinum 1", 1487);
const xprimeRageValue20 = xprimeRageProcessData("voe-2", "Platinum 2", 1486);
const xprimeRageValue21 = xprimeRageProcessData("fil", "Ruby", 1485);
const xprimeRageValue22 = xprimeRageProcessData("fil-1", "Ruby 1", 1484);
const xprimeRageValue23 = xprimeRageProcessData("fil-2", "Ruby 2", 1483);
const xprimeRageValue24 = xprimeRageProcessData("doo", "Sapphire", 1482);
const xprimeRageValue25 = xprimeRageProcessData("doo-1", "Sapphire 1", 1481);
const xprimeRageValue26 = xprimeRageProcessData("doo-2", "Sapphire 2", 1480);
const xprimeRageValue27 = xprimeRageProcessData("wis", "Opal", 1479);
const xprimeRageValue28 = xprimeRageProcessData("wis-1", "Opal 1", 1478);
const xprimeRageValue29 = xprimeRageProcessData("wis-2", "Opal 2", 1477);
const xprimeRageValue30 = xprimeRageProcessData("vsr", "Pearl", 1476);
const xprimeRageValue31 = xprimeRageProcessData("vsr-1", "Pearl 1", 1475);
const xprimeRageValue32 = xprimeRageProcessData("vsr-2", "Pearl 2", 1474);
const xprimeRageValue33 = xprimeRageProcessData("vxr", "Topaz", 1473);
const xprimeRageValue34 = xprimeRageProcessData("vxr-1", "Topaz 1", 1472);
const xprimeRageValue35 = xprimeRageProcessData("vxr-2", "Topaz 2", 1471);
const xprimeRageValue36 = xprimeRageProcessData("vrk", "Jade", 1470);
const xprimeRageValue37 = xprimeRageProcessData("vrk-1", "Jade 1", 1469);
const xprimeRageValue38 = xprimeRageProcessData("vrk-2", "Jade 2", 1468);
const xprimeRageValue39 = xprimeRageProcessData("mix", "Onyx", 1467);
const xprimeRageValue40 = xprimeRageProcessData("mix-1", "Onyx 1", 1466);
const xprimeRageValue41 = xprimeRageProcessData("mix-2", "Onyx 2", 1465);
const xprimeRageValue42 = xprimeRageProcessData("mol", "Garnet", 1464);
const xprimeRageValue43 = xprimeRageProcessData("mol-1", "Garnet 1", 1463);
const xprimeRageValue44 = xprimeRageProcessData("mol-2", "Garnet 2", 1462);
const xprimeRageValue45 = xprimeRageProcessData("lul", "Amethyst", 1461);
const xprimeRageValue46 = xprimeRageProcessData("lul-1", "Amethyst 1", 1460);
const xprimeRageValue47 = xprimeRageProcessData("lul-2", "Amethyst 2", 1459);
function xprimeRageProcessData3() {
    if (typeof navigator === "undefined") {
        return "unknown";
    }
    const value = navigator.userAgent.toLowerCase();
    return value.includes("chrome") && !value.includes("edg") ? "chrome" : value.includes("firefox") ? "firefox" : value.includes("safari") && !value.includes("chrome") ? "safari" : "unknown";
}
function xprimeRageProcessData4() {
    return xprimeRageProcessData3() === "chrome";
}
async function scrapeXprimeRage(context) {
    const data = JSON.parse(context.url);
    let value = xprimeRageBaseUrl10 + "?id=" + data.tmdbId;
    if (data.type === "show" && (value += "&season=" + data.season + "&episode=" + data.episode), !xprimeRageProcessData4()) {
        throw new ScraperError("Rage embed only works on Chrome/Brave browsers");
    }
    const response = await context.fetcher(value);
    if (!response) {
        throw new ScraperError("No response received");
    }
    if (response.error) {
        throw new ScraperError(response.error);
    }
    if (!response.url && !(Array.isArray(response.qualities) &&
        response.qualities.length
            >
                0)) {
        throw new ScraperError("No stream URL found in response");
    }
    const result = {};
    if (Array.isArray(response.qualities) &&
        response.qualities.length
            >
                0) {
        for (const item of response.qualities) {
            if (!(item != null && item.url) || !(item != null && item.quality)) {
                continue;
            }
            const value5 = String(item.quality).toUpperCase();
            if (value5 === "4K" ||
                value5 === "2160P" ||
                value5 === "P2160") {
                result["4K"] = item.url;
                continue;
            }
            const match = value5.match(/(\d{3,4})/);
            if (match) {
                (result[match[1] + "P"] = item.url);
            }
        }
    }
    else if (response.url) {
        if (typeof response.quality
            === "string") {
            const value6 = response.quality.toUpperCase();
            if (value6 ===
                "4K"
                ||
                    value6 ===
                        "2160P" ||
                value6 === "P2160") {
                result["4K"] = response.url;
            }
            else {
                const match5 = value6.match(/(\d{3,4})/);
                match5 ? result[match5[1] + "P"] = response.url : result.ORG = response.url;
            }
        }
        else {
            result.ORG = response.url;
        }
    }
    const numericValue = Object.entries(result).reduce((accumulator, [s, u]) => {
        let value;
        if (s
            ===
                "ORG") {
            return u.split("?")[0].toLowerCase().endsWith(".mp4") && (accumulator.unknown = u), accumulator;
        }
        if (s
            ===
                "4K") {
            value = 2160;
        }
        else {
            value =
                parseInt(s.replace("P", ""), 10);
        }
        Number.isNaN(value) || accumulator[value] || (accumulator[value] = u);
        return accumulator;
    }, {});
    context.progress(90);
    const stream = {
        id: "primary",
        captions: [],
        qualities: { ...numericValue[2160] && { "4k": { type: "mp4", url: numericValue[2160] } }, ...numericValue[1080] && { 1080: { type: "mp4", url: numericValue[1080] } }, ...numericValue[720] && { 720: { type: "mp4", url: numericValue[720] } }, ...numericValue[480] && { 480: { type: "mp4", url: numericValue[480] } }, ...numericValue[360] && { 360: { type: "mp4", url: numericValue[360] } }, ...numericValue.unknown && { unknown: { type: "mp4", url: numericValue.unknown } } },
        type: "file",
        flags: ["cors-allowed"]
    };
    return {
        stream: [stream]
    };
}
async function scrapeXprimeApollo(context) {
    var temporaryValue;
    var temporaryValue3;
    const data = JSON.parse(context.url);
    let value = xprimeRageBaseUrl2 + "/" + data.tmdbId;
    if (data.type === "show") {
        (value += "/" + data.season + "/" + data.episode);
    }
    const response = await context.fetcher(value);
    if (!response) {
        throw new ScraperError("No response received");
    }
    if (response.error) {
        throw new ScraperError(response.error);
    }
    if (!response.url) {
        throw new ScraperError("No stream URL found in response");
    }
    const language = ((temporaryValue = response.subtitles) == null ? void 0 : temporaryValue.map((item, index) => ({ id: index, type: "vtt", url: item.file, language: normalizeLanguageCode(item.label) || "unknown" }))) || [];
    context.progress(90);
    const stream = { type: "hls", id: "primary", playlist: response.url, flags: ["cors-allowed"], captions: language, ...(temporaryValue3 = response.thumbnails) != null && temporaryValue3.file ? { thumbnailTrack: { type: "vtt", url: response.thumbnails.file } } : {} };
    return {
        stream: [stream]
    };
}
async function scrapeXprimeStreambox(context) {
    var temporaryValue;
    const data = JSON.parse(context.url);
    let value = xprimeRageBaseUrl3 + "?name=" + data.title + "&year=" + data.releaseYear + "&fallback_year=" + data.releaseYear;
    if (data.type === "show") {
        (value += "&season=" + data.season + "&episode=" + data.episode);
    }
    const response = await context.fetcher(value);
    if (!response) {
        throw new ScraperError("No response received");
    }
    if (response.error) {
        throw new ScraperError(response.error);
    }
    if (!response.streams) {
        throw new ScraperError("No streams found in response");
    }
    const language = ((temporaryValue = response.subtitles) == null ? void 0 : temporaryValue.map((item, index) => ({ id: index, url: item.file, language: normalizeLanguageCode(item.label) || "unknown", type: "srt" }))) || [];
    const result = {};
    Object.entries(response.streams).forEach(([u, h]) => {
        const value = u.toUpperCase();
        let value3;
        if (value === "4K" ? value3 = 2160 : value3 = parseInt(value.replace("P", ""), 10), !Number.isNaN(value3) && !result[value3]) {
            result[value3] = h;
        }
    });
    const stream = {
        id: "primary",
        captions: language,
        qualities: { ...result[2160] && { "4k": { type: "mp4", url: result[2160] } }, ...result[1080] && { 1080: { type: "mp4", url: result[1080] } }, ...result[720] && { 720: { type: "mp4", url: result[720] } }, ...result[480] && { 480: { type: "mp4", url: result[480] } }, ...result[360] && { 360: { type: "mp4", url: result[360] } } },
        type: "file",
        flags: ["cors-allowed"]
    };
    return {
        stream: [stream]
    };
}
async function scrapeXprimeFox(context) {
    var temporaryValue;
    const data = JSON.parse(context.url);
    const result = {
        id: data.tmdbId
    };
    const queryParams = new URLSearchParams(result);
    if (data.type === "show") {
        (queryParams.append("season", data.season.toString()), queryParams.append("episode", data.episode.toString()));
    }
    const response = await context.fetcher(xprimeRageBaseUrl + "?" + queryParams.toString());
    if (!response) {
        throw new ScraperError("No response received");
    }
    const data3 = JSON.parse(response);
    if (!data3.url) {
        throw new ScraperError("No stream URL found in response");
    }
    const language = ((temporaryValue = data3.subtitles) == null ? void 0 : temporaryValue.map((item, index) => {
        const normalizedLanguage = item.label.split(" ")[0].toLowerCase();
        return { id: index, type: "vtt", url: item.file, language: normalizeLanguageCode(normalizedLanguage)
                || "unknown" };
    })) || [];
    context.progress(90);
    const stream = {
        type: "hls",
        id: "primary",
        playlist: data3.url,
        flags: ["cors-allowed"],
        captions: language
    };
    return {
        stream: [stream]
    };
}
async function scrapeXprimePrimenet(context) {
    const data = JSON.parse(context.url);
    let value = xprimeRageBaseUrl6 + "?id=" + data.tmdbId;
    if (data.type === "show") {
        (value += "&season=" + data.season + "&episode=" + data.episode);
    }
    const response = await context.fetcher(value);
    if (!response) {
        throw new ScraperError("No response received");
    }
    if (response.error) {
        throw new ScraperError(response.error);
    }
    if (!response.url) {
        throw new ScraperError("No stream URL found in response");
    }
    context.progress(90);
    const stream = {
        type: "hls",
        id: "primary",
        playlist: response.url,
        flags: ["cors-allowed"],
        captions: []
    };
    return {
        stream: [stream]
    };
}
async function scrapeXprimeKraken(context) {
    var temporaryValue;
    const data = JSON.parse(context.url);
    let value = xprimeRageBaseUrl5 + "?id=" + data.tmdbId + "&name=" + encodeURIComponent(data.title);
    if (data.type === "show") {
        value += "&season=" + data.season + "&episode=" + data.episode + "&eid=" + (data.episodeId || "");
    }
    const response = await context.fetcher(value);
    if (!response) {
        throw new ScraperError("No response received");
    }
    if (response.error) {
        throw new ScraperError(response.error);
    }
    if (!response.url) {
        throw new ScraperError("No stream URL found in response");
    }
    const language = ((temporaryValue = response.subtitles) == null ? void 0 : temporaryValue.map((item, index) => ({ id: index, type: "vtt", url: item.file, language: normalizeLanguageCode(item.label) || "unknown" }))) || [];
    context.progress(90);
    const stream = {
        type: "hls",
        id: "primary",
        playlist: response.url,
        flags: ["cors-allowed"],
        captions: language
    };
    return {
        stream: [stream]
    };
}
async function scrapeXprimePhoenix(context) {
    const data = JSON.parse(context.url);
    const queryParams = new URLSearchParams;
    if (queryParams.append("id", data.tmdbId), queryParams.append("imdb", data.imdbId), data.type === "show") {
        queryParams.append("season", data.season.toString()), queryParams.append("episode", data.episode.toString());
    }
    const value = xprimeRageBaseUrl11 + "?" + queryParams.toString();
    context.progress(50);
    const response = await context.fetcher(value);
    if (!response) {
        throw new ScraperError("No response received");
    }
    if (response.error) {
        throw new ScraperError(response.error);
    }
    if (!response.url) {
        throw new ScraperError("No stream URL found in response");
    }
    context.progress(90);
    const language = response.subtitles ? response.subtitles.map((item, index) => {
        const parts = item.label.split(" ")[0];
        const language = normalizeLanguageCode(parts)
            || parts.toLowerCase().substring(0, 2);
        return {
            id: index,
            language: language,
            url: item.file,
            label: item.label,
            type: "vtt"
        };
    }) : [];
    const stream = {
        type: "hls",
        id: "primary",
        playlist: response.url,
        flags: ["cors-allowed"],
        captions: language
    };
    return {
        stream: [stream]
    };
}
async function scrapeXprimeHarbour(context) {
    var temporaryValue;
    const data = JSON.parse(context.url);
    const queryParams = new URLSearchParams({ name: data.title, year: data.releaseYear.toString() });
    if (data.type === "show") {
        (queryParams.append("season", data.season.toString()), queryParams.append("episode", data.episode.toString()));
    }
    const response = await context.fetcher(xprimeRageBaseUrl8 + "?" + queryParams.toString());
    if (!response) {
        throw new ScraperError("No response received");
    }
    const data3 = await JSON.parse(response);
    if (!data3.url) {
        throw new ScraperError("No stream URL found in response");
    }
    const language = ((temporaryValue = data3.subtitles) == null ? void 0 : temporaryValue.map((item, index) => ({ id: index, type: "vtt", url: item.file, language: normalizeLanguageCode(item.label) || "unknown" }))) || [];
    context.progress(90);
    const stream = {
        type: "hls",
        id: "primary",
        playlist: data3.url,
        flags: ["cors-allowed"],
        captions: language
    };
    return {
        stream: [stream]
    };
}
async function scrapeXprimeFendi(context) {
    const data = JSON.parse(context.url);
    let value = xprimeRageBaseUrl9 + "?id=" + data.tmdbId;
    if (data.type === "show") {
        (value += "&season=" + data.season + "&episode=" + data.episode);
    }
    const response = await context.fetcher(value);
    if (!response) {
        throw new ScraperError("No response received");
    }
    if (response.error) {
        throw new ScraperError(response.error);
    }
    if (!response.url) {
        throw new ScraperError("No stream URL found in response");
    }
    context.progress(90);
    const stream = {
        type: "hls",
        id: "primary",
        playlist: response.url,
        flags: ["cors-allowed"],
        captions: []
    };
    return {
        stream: [stream]
    };
}
async function scrapeXprimeMarant(context) {
    const data = JSON.parse(context.url);
    let value = xprimeRageBaseUrl4 + "?id=" + data.tmdbId;
    if (data.type === "show") {
        value += "&season=" + data.season + "&episode=" + data.episode;
    }
    const response = await context.fetcher(value);
    if (!response) {
        throw new ScraperError("No response received");
    }
    if (response.error) {
        throw new ScraperError(response.error);
    }
    if (!response.url) {
        throw new ScraperError("No stream URL found in response");
    }
    context.progress(90);
    const stream = {
        type: "hls",
        id: "primary",
        playlist: response.url,
        flags: ["cors-allowed"],
        captions: []
    };
    return {
        stream: [stream]
    };
}
async function scrapeXprimeVolkswagen(context) {
    const data = JSON.parse(context.url);
    let value = xprimeRageBaseUrl7 + "?name=" + data.title;
    if (data.type === "show") {
        value += "&season=" + data.season + "&episode=" + data.episode;
    }
    else {
        value += "&year=" + data.releaseYear;
    }
    const response = await context.fetcher(value);
    if (!response) {
        throw new ScraperError("No response received");
    }
    if (response.error) {
        throw new ScraperError(response.error);
    }
    if (!response.streams) {
        throw new ScraperError("No streams found in response");
    }
    const result = {};
    Object.entries(response.streams).forEach(([W, b]) => {
        const normalizedValue = W.toLowerCase().replace("p", "");
        const result = {
            type: "mp4",
            url: b
        };
        result[normalizedValue] = result;
    });
    context.progress(90);
    const stream = {
        id: "primary",
        type: "file",
        flags: ["cors-allowed"],
        qualities: result,
        captions: []
    };
    const result2 = {
        stream: [stream]
    };
    return result2;
}
const xprimeRageBaseUrl = "https://backend.xprime.tv/fox";
const xprimeRageBaseUrl2 = "https://kendrickl-3amar.site";
const xprimeRageBaseUrl3 = "https://backend.xprime.tv/primebox";
const xprimeRageBaseUrl4 = "https://backend.xprime.tv/marant";
const xprimeRageBaseUrl5 = "https://backend.xprime.tv/kraken";
const xprimeRageBaseUrl6 = "https://backend.xprime.tv/primenet";
const xprimeRageBaseUrl7 = "https://backend.xprime.tv/volkswagen";
const xprimeRageBaseUrl8 = "https://backend.xprime.tv/harbour";
const xprimeRageBaseUrl9 = "https://backend.xprime.tv/fendi";
const xprimeRageBaseUrl10 = "https://backend.xprime.tv/rage";
const xprimeRageBaseUrl11 = "https://backend.xprime.tv/phoenix";
const xprimeRageEmbedProvider = createEmbedProvider({ id: "xprime-rage", name: "Rage (4K)", rank: 249, scrape: scrapeXprimeRage });
const xprimeApolloEmbedProvider = createEmbedProvider({ id: "xprime-apollo", name: "Appolo", disabled: true, rank: 248, scrape: scrapeXprimeApollo });
const xprimeStreamboxEmbedProvider = createEmbedProvider({ id: "xprime-streambox", name: "Streambox", rank: 247, scrape: scrapeXprimeStreambox });
const xprimeFoxEmbedProvider = createEmbedProvider({ id: "xprime-fox", name: "Fox", rank: 246, scrape: scrapeXprimeFox });
const xprimePrimenetEmbedProvider = createEmbedProvider({ id: "xprime-primenet", name: "Primenet", rank: 245, scrape: scrapeXprimePrimenet });
const xprimeKrakenEmbedProvider = createEmbedProvider({ id: "xprime-kraken", name: "Kraken", rank: 244, disabled: true, scrape: scrapeXprimeKraken });
const xprimePhoenixEmbedProvider = createEmbedProvider({ id: "xprime-phoenix", name: "Phoenix", rank: 243, scrape: scrapeXprimePhoenix });
const xprimeHarbourEmbedProvider = createEmbedProvider({ id: "xprime-harbour", name: "Harbour", disabled: true, rank: 242, scrape: scrapeXprimeHarbour });
const xprimeFendiEmbedProvider = createEmbedProvider({ id: "xprime-fendi", name: "Fendi (Italian + English)", rank: 240, disabled: true, scrape: scrapeXprimeFendi });
const xprimeMarantEmbedProvider = createEmbedProvider({ id: "xprime-marant", name: "Marant (French + English)", rank: 239, disabled: true, scrape: scrapeXprimeMarant });
const xprimeVolkswagenEmbedProvider = createEmbedProvider({ id: "xprime-volkswagen", name: "Volkswagen (German)", rank: 238, disabled: true, scrape: scrapeXprimeVolkswagen });
const oneserverValue = ["hd-2", "miko", "shiro", "zaza"];
const oneserverBaseUrl = "https://backend.xaiby.sbs";
const oneserverValue2 = {
    referer: "https://vidnest.fun/",
    origin: "https://vidnest.fun",
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
};
const oneserverValue3 = oneserverValue2;
function oneserverResolveStream(context, key = 100) {
    return createEmbedProvider({ id: "zunime-" + context, name: "" + (context.charAt(0).toUpperCase() + context.slice(1)), rank: key, scrape: async function scrapeOneserverResolveStream(context) {
            var url;
            var value;
            const value2 = context;
            const data = JSON.parse(context.url);
            const { anilistId: anilistId2, episode: episode2 } = data;
            const sourcesUrl = await context.proxiedFetcher("/sources", { baseUrl: oneserverBaseUrl, headers: oneserverValue3, query: { id: String(anilistId2), ep: String(episode2 ?? 1), host: value2, type: "dub" } });
            const url3 = sourcesUrl;
            if (!(url3 != null && url3.success) || !((url = url3?.sources) != null && url.url)) {
                throw new ScraperError("No stream URL found in response");
            }
            const url4 = url3.sources.url;
            const url5 = (value = url3?.sources) != null && value.headers &&
                Object.keys(url3.sources.headers).length
                    >
                        0 ? url3.sources.headers : oneserverValue3;
            context.progress(100);
            return { stream: [{ id: "primary", type: "hls", playlist: buildProxiedHlsUrl("https://proxy-2.madaraverse.online/proxy?url=" + encodeURIComponent(url4), context.features, url5), headers: url5, flags: ["cors-allowed"], captions: [] }] };
        } });
}
const oneserverValue4 = oneserverValue.map((item, index) => oneserverResolveStream(item, 260 - index));
async function scrapeOneserver(context) {
    const value = { type: context.media.type, title: context.media.title, tmdbId: context.media.tmdbId.toString(), ...context.media.type === "show" && { season: context.media.season.number, episode: context.media.episode.number } };
    const streams = [{ embedId: "oneserver-autoembed", url: JSON.stringify(value) }, { embedId: "oneserver-vidsrcsu", url: JSON.stringify(value) }, { embedId: "oneserver-primebox", url: JSON.stringify(value) }, { embedId: "oneserver-foxstream", url: JSON.stringify(value) }, { embedId: "oneserver-flixhq", url: JSON.stringify(value) }, { embedId: "oneserver-goku", url: JSON.stringify(value) }];
    return {
        embeds: streams
    };
}
const oneserverProviderConfig = {
    id: "1server",
    name: "1Server \u2601\uFE0F",
    rank: 90,
    disabled: true,
    flags: ["cors-allowed"],
    scrapeMovie: scrapeOneserver,
    scrapeShow: scrapeOneserver
};
const oneserverProvider = createSourceProvider(oneserverProviderConfig);
async function oneserverResolveStream2(context, key2) {
    try {
        const requestUrl = "https://ftmoh345xme.com";
        const requestOptions = {
            Origin: "https://friness-cherlormur-i-275.site",
            Referer: "https://google.com/",
            Dnt: "1"
        };
        const value = requestOptions;
        const url = requestUrl + "/play/" + key2;
        const requestOptions2 = { ...value };
        const requestOptions3 = {
            headers: requestOptions2,
            method: "GET"
        };
        const response = await context.proxiedFetcher(url, requestOptions3);
        const value7 = ZH.load(response);
        const value8 = value7("script").last().html();
        if (!value8) {
            throw new ScraperError("Failed to extract script data");
        }
        const match = (value8.match(/(\{[^;]+});/)?.[1]) || (value8.match(/\((\{.*\})\)/)?.[1]);
        if (!match) {
            throw new ScraperError("Media not found");
        }
        const data = JSON.parse(match);
        let file2 = data.file;
        if (!file2) {
            throw new ScraperError("File not found");
        }
        if (file2.startsWith("/")) {
            file2 =
                requestUrl + file2;
        }
        const key3 = data.key;
        const requestOptions4 = {
            Origin: "https://friness-cherlormur-i-275.site",
            Referer: "https://google.com/",
            Dnt: "1",
            "X-Csrf-Token": key3
        };
        const value9 = requestOptions4;
        const requestOptions5 = { ...value9 };
        const requestOptions6 = {
            headers: requestOptions5,
            method: "GET"
        };
        const response2 = await context.proxiedFetcher(file2, requestOptions6);
        const value10 = response2;
        const stream = {
            playlist: value10,
            key: key3
        };
        return {
            success: true,
            data: stream
        };
    }
    catch (temporaryValue5) {
        throw temporaryValue5 instanceof ScraperError
            ? temporaryValue5 : new ScraperError("Failed to fetch media info");
    }
}
async function eightstreamResolveStream(context, argument2, argument3) {
    const value = argument2;
    const url = value.slice(1) + ".txt";
    try {
        const requestUrl = "https://ftmoh345xme.com";
        const requestOptions = {
            Origin: "https://friness-cherlormur-i-275.site",
            Referer: "https://google.com/",
            Dnt: "1",
            "X-Csrf-Token": argument3
        };
        const value4 = requestOptions;
        const playlistUrl = requestUrl + "/playlist/" + url;
        const requestOptions2 = { ...value4 };
        const requestOptions3 = {
            headers: requestOptions2,
            method: "GET"
        };
        const response = await context.proxiedFetcher(playlistUrl, requestOptions3);
        const result = {
            link: response
        };
        return {
            success: true,
            data: result
        };
    }
    catch {
        throw new ScraperError("Failed to fetch stream data");
    }
}
async function eightstreamParseHtml(input, language, language2 = "English") {
    try {
        {
            const value = await oneserverResolveStream2(input, language);
            if (value != null && value.success) {
                const playlistUrl = value?.data?.playlist;
                if (!playlistUrl || !Array.isArray(playlistUrl)) {
                    throw new ScraperError("Playlist not found or invalid");
                }
                let item = playlistUrl.find(item => (item?.title) === language2);
                if (!item && (item = playlistUrl?.[0]), !item) {
                    throw new ScraperError("No file found");
                }
                const items = playlistUrl.map(item => item?.title);
                const value4 = value?.data?.key;
                input.progress(70);
                const value5 = await eightstreamResolveStream(input, item?.file, value4);
                if (value5 != null && value5.success) {
                    return {
                        success: true,
                        data: value5?.data,
                        availableLang: items
                    };
                }
                throw new ScraperError("No stream url found");
            }
            throw new ScraperError("No media info found");
        }
    }
    catch (temporaryValue5) {
        throw temporaryValue5 instanceof ScraperError
            ? temporaryValue5 : new ScraperError("Failed to fetch movie data");
    }
}
async function eightstreamParseHtml2(input, language, language2, language3, language4) {
    try {
        const value = await oneserverResolveStream2(input, language);
        if (!(value != null && value.success)) {
            throw new ScraperError("No media info found");
        }
        const playlistUrl = value?.data?.playlist;
        const item = playlistUrl.find(item => (item?.id) === language2.toString());
        if (!item) {
            throw new ScraperError("No season found");
        }
        const match = item == null ? void 0 : item.folder.find(item => (item?.episode) === language3.toString());
        if (!match) {
            throw new ScraperError("No episode found");
        }
        let match2 = match == null ? void 0 : match.folder.find(item => (item?.title) === language4);
        if (!match2 && (match2 = match?.folder?.[0]), !match2) {
            throw new ScraperError("No file found");
        }
        const items = match == null ? void 0 : match.folder.map(item => {
            return item?.title;
        });
        const filteredItems = items.filter(item => (item?.length) > 0);
        const value4 = value?.data?.key;
        input.progress(70);
        const value5 = await eightstreamResolveStream(input, match2?.file, value4);
        if (value5 != null && value5.success) {
            ;
            {
                return {
                    success: true,
                    data: value5?.data,
                    availableLang: filteredItems
                };
            }
        }
        throw new ScraperError("No stream url found");
    }
    catch (temporaryValue7) {
        throw temporaryValue7 instanceof ScraperError ? temporaryValue7 : new ScraperError("Failed to fetch TV data");
    }
}
async function scrapeEightstream(context) {
    const stream = {};
    if (stream.title = context.media.title, stream.releaseYear = context.media.releaseYear, stream.tmdbId = context.media.tmdbId, stream.imdbId = context.media.imdbId, stream.type = context.media.type, stream.season = "", stream.episode = "", context.media.type === "show" && (context.media.season.number.toString(), context.media.episode.number.toString()), context.media.type === "movie") {
        context.progress(40);
        const value = await eightstreamParseHtml(context, context.media.imdbId);
        if (value != null && value.success) {
            context.progress(90);
            const stream3 = {
                id: "primary",
                captions: [],
                playlist: value.data.link,
                type: "hls",
                flags: ["cors-allowed"]
            };
            return {
                embeds: [],
                stream: [stream3]
            };
        }
        throw new ScraperError("No providers available");
    }
    if (context.media.type === "show") {
        context.progress(40);
        const value4 = "English";
        const value5 = await eightstreamParseHtml2(context, context.media.imdbId, context.media.season.number, context.media.episode.number, value4);
        if (value5 != null && value5.success) {
            context.progress(90);
            const stream4 = {
                id: "primary",
                captions: [],
                playlist: value5.data.link,
                type: "hls",
                flags: ["cors-allowed"]
            };
            return {
                embeds: [],
                stream: [stream4]
            };
        }
        throw new ScraperError("No providers available");
    }
    throw new ScraperError("No providers available");
}
const eightstreamProviderConfig = {
    id: "8stream",
    name: "8Stream \uD83C\uDFB1",
    rank: 111,
    flags: [],
    disabled: true,
    scrapeMovie: scrapeEightstream,
    scrapeShow: scrapeEightstream
};
const eightstreamProvider = createSourceProvider(eightstreamProviderConfig);
const animeflvNetHosts = ["https://www4.animeflv.net", "https://www3.animeflv.net"];
const animeflvMirrorHosts = ["https://animeflv.com.im", "https://animeflv.com.ro"];
const animeflvBrowserHeaders = {
    "User-Agent":
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    Accept: "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "es-ES,es;q=0.9,en;q=0.8",
};
function animeflvNormalizeTitle(value) {
    return String(value || "")
        .toLowerCase()
        .normalize("NFD")
        .replace(/[\u0300-\u036f]/g, "")
        .replace(/[^a-z0-9]+/g, " ")
        .trim();
}
function animeflvSlugify(value) {
    return animeflvNormalizeTitle(value).replace(/\s+/g, "-");
}
function animeflvScoreTitle(candidate, needle) {
    const a = animeflvNormalizeTitle(candidate);
    const b = animeflvNormalizeTitle(needle);
    if (!a || !b) return 0;
    if (a === b) return 100;
    if (a.startsWith(b) || b.startsWith(a)) return 80;
    if (a.includes(b) || b.includes(a)) return 60;
    const at = new Set(a.split(" "));
    const bt = b.split(" ").filter(Boolean);
    const hits = bt.filter((t) => at.has(t)).length;
    return bt.length ? (hits / bt.length) * 50 : 0;
}
async function animeflvGet(context, url) {
    return context.proxiedFetcher(url, { headers: { ...animeflvBrowserHeaders, Referer: url } });
}
async function animeflvSearchNet(context, title) {
    const queries = [title];
    if (context.media.type === "show" && context.media.season?.number > 1) {
        queries.push(`${title} ${context.media.season.number}`);
        queries.push(`${title} season ${context.media.season.number}`);
    }
    for (const host of animeflvNetHosts) {
        for (const query of queries) {
            try {
                const html = await animeflvGet(context, `${host}/browse?q=${encodeURIComponent(query)}`);
                const document = loadHtml(html);
                const seen = new Set();
                const hits = [];
                document("ul.ListAnimes li, .ListAnimes li").each((_i, el) => {
                    const node = document(el);
                    const href = String(node.find("a[href*='/anime/']").attr("href") || "");
                    const match = href.match(/\/anime\/([^/?#]+)/i);
                    if (!match || seen.has(match[1])) return;
                    seen.add(match[1]);
                    const name =
                        node.find("h3").first().text().trim() ||
                        node.find("img").attr("alt") ||
                        node.find(".Title, .title").first().text().trim() ||
                        match[1];
                    hits.push({ slug: match[1], title: name.replace(/\s+/g, " ").trim(), host });
                });
                if (!hits.length) {
                    document("a[href*='/anime/']").each((_i, el) => {
                        const href = String(document(el).attr("href") || "");
                        const match = href.match(/\/anime\/([^/?#]+)/i);
                        if (!match || seen.has(match[1])) return;
                        seen.add(match[1]);
                        const name =
                            document(el).attr("title") ||
                            document(el).find("img").attr("alt") ||
                            match[1];
                        hits.push({ slug: match[1], title: String(name).trim(), host });
                    });
                }
                if (!hits.length) continue;
                hits.sort((a, b) => animeflvScoreTitle(b.title, title) - animeflvScoreTitle(a.title, title));
                const best = hits[0];
                if (animeflvScoreTitle(best.title, title) >= 40) return { ...best, candidates: hits.slice(0, 8) };
            } catch {
                /* try next */
            }
        }
    }
    return null;
}
function animeflvParseVideos(html) {
    const embeds = [];
    const match = String(html || "").match(/var\s+videos\s*=\s*(\{[\s\S]*?\}|\[[\s\S]*?\])\s*;/);
    if (!match) return embeds;
    let data;
    try {
        data = JSON.parse(match[1]);
    } catch {
        return embeds;
    }
    const rows = [];
    if (Array.isArray(data)) rows.push(...data);
    else if (data && typeof data === "object") {
        for (const value of Object.values(data)) {
            if (Array.isArray(value)) rows.push(...value);
        }
    }
    for (const row of rows) {
        const url = String(row?.code || row?.url || row?.file || "").trim();
        if (!/^https?:\/\//i.test(url)) continue;
        const server = String(row?.server || row?.title || url).toLowerCase();
        const embedId = animeflvMapEmbedId(server, url);
        if (!embedId) continue;
        if (!embeds.some((item) => item.embedId === embedId && item.url === url)) {
            embeds.push({ embedId, url });
        }
    }
    return embeds;
}
function animeflvMapEmbedId(server, url) {
    const hay = `${server} ${url}`.toLowerCase();
    if (hay.includes("zilla-networks") || hay.includes("zilla")) return "zilla";
    if (hay.includes("streamtape") || /\bstape\b/.test(hay) || hay.includes("streamta.pe")) return "streamtape";
    if (hay.includes("streamwish") || /\bsw\b/.test(server) || hay.includes("wish")) {
        return "streamwish-japanese";
    }
    return null;
}
function animeflvExtractMirrorEmbeds(html) {
    const embeds = [];
    const text = String(html || "");
    const urls = new Set();
    for (const match of text.matchAll(/(?:data-litespeed-src|data-src|src|href)=["'](https?:\/\/[^"']+)["']/gi)) {
        urls.add(match[1]);
    }
    for (const match of text.matchAll(/https?:\/\/(?:player\.)?zilla-networks\.com\/(?:play|m3u8)\/[a-f0-9]{32}/gi)) {
        urls.add(match[0].startsWith("http") ? match[0] : `https://${match[0]}`);
    }
    for (const match of text.matchAll(/(?:player\.)?zilla-networks\.com\/(?:play|m3u8)\/[a-f0-9]{32}/gi)) {
        urls.add(`https://${match[0].replace(/^https?:\/\//i, "")}`);
    }
    for (const match of text.matchAll(/https?:\/\/(?:www\.)?(?:streamtape|streamta)\.(?:com|pe)\/[^\s"'<>]+/gi)) {
        urls.add(match[0]);
    }
    for (const match of text.matchAll(/https?:\/\/(?:[\w.-]+\.)?(?:streamwish|strwish)[^/\s"'<>]*\/(?:e|v)\/[^\s"'<>]+/gi)) {
        urls.add(match[0]);
    }
    for (const url of urls) {
        const embedId = animeflvMapEmbedId("", url);
        if (!embedId) continue;
        if (!embeds.some((item) => item.embedId === embedId && item.url === url)) {
            embeds.push({ embedId, url });
        }
    }
    return embeds;
}
async function animeflvScrapeNetEpisode(context, host, slug, episode) {
    try {
        const html = await animeflvGet(context, `${host}/ver/${slug}-${episode}`);
        return animeflvParseVideos(html);
    } catch {
        return [];
    }
}
async function animeflvSearchMirrorEpisode(context, title, episode) {
    const queries = [
        `${title} episodio ${episode}`,
        `${title} ${episode}`,
        title,
    ];
    for (const host of animeflvMirrorHosts) {
        for (const query of queries) {
            try {
                const raw = await animeflvGet(
                    context,
                    `${host}/wp-json/wp/v2/posts?search=${encodeURIComponent(query)}&per_page=20`,
                );
                let posts;
                try {
                    posts = JSON.parse(raw);
                } catch {
                    continue;
                }
                if (!Array.isArray(posts) || !posts.length) continue;
                const ranked = posts
                    .map((post) => {
                        const link = String(post?.link || "");
                        const slug = String(post?.slug || "");
                        const postTitle = String(post?.title?.rendered || "")
                            .replace(/<[^>]+>/g, " ")
                            .replace(/\s+/g, " ")
                            .trim();
                        const epMatch = slug.match(/episodio-(\d+)/i) || postTitle.match(/episodio\s*(\d+)/i);
                        const epNum = epMatch ? Number(epMatch[1]) : 0;
                        let score = animeflvScoreTitle(postTitle, title);
                        if (epNum === Number(episode)) score += 40;
                        if (slug.includes(animeflvSlugify(title).slice(0, 18))) score += 10;
                        return { link, slug, title: postTitle, score, epNum };
                    })
                    .filter((item) => item.link && item.score >= 40)
                    .sort((a, b) => b.score - a.score);
                const hit = ranked.find((item) => item.epNum === Number(episode)) || ranked[0];
                if (!hit || hit.epNum !== Number(episode)) continue;
                const html = await animeflvGet(context, hit.link);
                const embeds = animeflvExtractMirrorEmbeds(html);
                if (embeds.length) return embeds;
            } catch {
                /* try next */
            }
        }
    }
    return [];
}
async function animeflvScrapeMirrorEpisode(context, slug, episode, title) {
    const slugs = [slug];
    if (slug && !/-part-\d+$/i.test(slug)) {
        for (let part = 1; part <= 4; part += 1) slugs.push(`${slug}-part-${part}`);
    }
    if (title) {
        const alt = animeflvSlugify(title);
        if (alt && !slugs.includes(alt)) slugs.push(alt);
    }
    for (const host of animeflvMirrorHosts) {
        for (const item of slugs) {
            try {
                const html = await animeflvGet(context, `${host}/${item}-episodio-${episode}/`);
                if (!html || /error\s*404|not\s*found|no\s*encontrad/i.test(html)) continue;
                const embeds = animeflvExtractMirrorEmbeds(html);
                if (embeds.length) return embeds;
            } catch {
                /* try next */
            }
        }
    }
    if (title) return animeflvSearchMirrorEpisode(context, title, episode);
    return [];
}
async function scrapeAnimeflv(context) {
    const title2 = context.media.title;
    if (!title2) throw new ScraperError("Missing title");
    const episode =
        context.media.type === "show"
            ? Number(context.media.episode?.number || 0)
            : 1;
    if (!episode) throw new ScraperError("Missing episode data");

    const hit = (await animeflvSearchNet(context, title2)) || {
        slug: animeflvSlugify(title2),
        title: title2,
        host: animeflvNetHosts[0],
        candidates: [],
    };

    const slugTries = [
        hit.slug,
        ...(hit.candidates || []).map((item) => item.slug),
    ].filter((value, index, all) => value && all.indexOf(value) === index);

    let embeds = [];
    for (const slug of slugTries) {
        embeds = await animeflvScrapeNetEpisode(context, hit.host || animeflvNetHosts[0], slug, episode);
        if (embeds.length) break;
        for (const host of animeflvNetHosts) {
            if (host === hit.host) continue;
            embeds = await animeflvScrapeNetEpisode(context, host, slug, episode);
            if (embeds.length) break;
        }
        if (embeds.length) break;
    }

    if (!embeds.length) {
        for (const slug of slugTries) {
            embeds = await animeflvScrapeMirrorEpisode(context, slug, episode, title2);
            if (embeds.length) break;
        }
    }
    if (!embeds.length) {
        embeds = await animeflvSearchMirrorEpisode(context, title2, episode);
    }
    if (!embeds.length) throw new ScraperError("No valid embed found for this content");
    return { embeds };
}
const animeflvProviderConfig = {
    id: "animeflv",
    name: "AnimeFLV \uD83C\uDFEF",
    rank: 92,
    disabled: false,
    flags: ["cors-allowed"],
    scrapeShow: scrapeAnimeflv,
    scrapeMovie: scrapeAnimeflv
};
const animeflvProvider = createSourceProvider(animeflvProviderConfig);
const zillaEmbedProvider = createEmbedProvider({
    id: "zilla",
    name: "Zilla",
    rank: 165,
    scrape: async function scrapeZilla(context) {
        const match = String(context.url || "").match(/\/(?:play|m3u8)\/([a-f0-9]{32})/i);
        if (!match) throw new ScraperError("Invalid Zilla url");
        const playlist = `https://player.zilla-networks.com/m3u8/${match[1]}`;
        return {
            stream: [
                {
                    id: "primary",
                    type: "hls",
                    playlist,
                    flags: ["cors-allowed"],
                    captions: [],
                    headers: {
                        Referer: "https://player.zilla-networks.com/",
                        Origin: "https://player.zilla-networks.com",
                    },
                },
            ],
        };
    },
});
async function scrapeAnimetsuShow(context) {
    const value = await fsharetvLookupEpisode(context, context.media);
    const result = {
        episode: 1
    };
    const result2 = { type: context.media.type, title: context.media.title, tmdbId: context.media.tmdbId, imdbId: context.media.imdbId, anilistId: value, ...context.media.type === "show" && { season: context.media.season.number, episode: context.media.episode.number }, ...context.media.type === "movie" && result, releaseYear: context.media.releaseYear };
    return { embeds: [{ embedId: "animetsu-pahe", url: JSON.stringify(result2) }, { embedId: "animetsu-zoro", url: JSON.stringify(result2) }, { embedId: "animetsu-zaza", url: JSON.stringify(result2) }, { embedId: "animetsu-meg", url: JSON.stringify(result2) }, { embedId: "animetsu-bato", url: JSON.stringify(result2) }] };
}
const animetsuProviderConfig = {
    id: "animetsu",
    name: "Animetsu \uD83C\uDFEF",
    rank: 112,
    flags: ["cors-allowed"],
    scrapeShow: scrapeAnimetsuShow
};
function animetsuProcessData() {
    return "eyJ0eXAiOiJKV1QiLCJhbGciOiJIUzI1NiJ9.eyJpYXQiOjE3NDI5OTc4MTksIm5iZiI6MTc0Mjk5NzgxOSwiZXhwIjoxNzc0MTAxODM5LCJkYXRhIjp7InVpZCI6Njk2MzU5LCJ0b2tlbiI6IjUzNmNiZjI2NzA0Zjk4MjAxMjBiYjY4OTRlNjBmMmI2In19.RC8T4zyxxikVtuuEIxbYhYK8T_REhIcnC8AYzoS3jKY";
}
function ciaApiProcessData() {
    try {
        if (typeof window
            === "undefined") {
            return null;
        }
        const value = window.localStorage.getItem("__MW::region");
        if (!value) {
            return null;
        }
        const data = JSON.parse(value);
        return (data?.state?.region) ?? null;
    }
    catch (temporaryValue3) {
        console.warn("Unable to access localStorage or parse auth data:", temporaryValue3);
        return null;
    }
}
const animetsuProvider = createSourceProvider(animetsuProviderConfig);
function ciaApiSelectServer(input) {
    const value = (input || "").toLowerCase();
    if (/(^|\b)(usa5|usa6|usa7|uk1|de2|hk1|ca1|au1|sg1|in1)(\b|$)/.test(value)) {
        const match = value.match(/(usa5|usa6|usa7|uk1|de2|hk1|ca1|au1|sg1|in1)/);
        if (match) {
            return match[1];
        }
    }
    return value.includes("dallas") ? "usa5" : value.includes("portland") ? "usa6" : value.includes("new-york") ? "usa7" : value.includes("paris") ? Math.random()
        <
            0.5
        ? "uk1" : "de2" : value.includes("hong-kong") ? "hk1" : value.includes("kansas") ? Math.random()
        <
            0.5
        ? "usa7" : "usa6" : value.includes("sydney") ? "au1" : value.includes("singapore") ? "sg1" : value.includes("mumbai") ? "in1" : input ===
        "east"
        ? "usa7" : input === "west"
        ? "usa6" : input === "south"
        ? "usa5" : input === "europe"
        ? Math.random()
            <
                0.5
            ? "uk1" : "de2" : input === "asia"
        ? "sg1" : null;
}
function ciaApiGetFileExtension(input, argument2) {
    try {
        const parsedUrl = new URL(input);
        return parsedUrl.hostname.endsWith(".shegu.net") ? (parsedUrl.hostname = argument2 + ".shegu.net", parsedUrl.toString()) : input;
    }
    catch {
        return input;
    }
}
const ciaApiBaseUrl = "https://febbox.andresdev.org";
async function scrapeCiaApiMovie(context) {
    const value = animetsuProcessData();
    const url = ciaApiBaseUrl + "/m/" + context.media.imdbId;
    const requestOptions = {
        Origin: "https://pstream.mov",
        Referer: "https://pstream.mov",
        "ui-token": value
    };
    const value7 = requestOptions;
    const requestOptions2 = {
        headers: value7
    };
    const response = await context.proxiedFetcher(url, requestOptions2);
    if (response != null && response.error && response.error.startsWith("No results found")) {
        throw new ScraperError("No stream found");
    }
    if ((response?.error)
        === "No cached data found for this episode") {
        throw new ScraperError("No stream found");
    }
    if ((response?.error)
        === "No cached data found for this ID") {
        throw new ScraperError("No stream found");
    }
    if (!response) {
        throw new ScraperError("No response from API");
    }
    if (context.progress(50), !response.streams ||
        typeof response.streams
            !== "object" ||
        Object.keys(response.streams).length
            ===
                0) {
        throw new ScraperError("No streams data found in response");
    }
    const numericValue = Object.entries(response.streams).reduce((accumulator, [S, k]) => {
        if (typeof k
            !==
                "string"
            || k.includes("/video/vip_only.mp4")) {
            return accumulator;
        }
        let value;
        return S
            === "ORG[HDR]"
            ||
                S
                    === "ORG" ? (k.split("?")[0].toLowerCase().endsWith(".mp4") && (accumulator.unknown = k), accumulator) : (S
            ===
                "4K"
            ? value = "2160" : value = S.replace("P", ""), Number.isNaN(parseInt(value, 10)) || accumulator[value] || (accumulator[value] = k), accumulator);
    }, {});
    const value8 = ciaApiProcessData();
    const value9 = ciaApiSelectServer(value8);
    value9 && Object.keys(numericValue).forEach(item => {
        numericValue[item] =
            ciaApiGetFileExtension(numericValue[item], value9);
    });
    context.progress(90);
    const stream = {
        id: "primary",
        captions: [],
        qualities: { ...numericValue["2160"] && { "4k": { type: "mp4", url: numericValue["2160"] } }, ...numericValue["1080"] && { 1080: { type: "mp4", url: numericValue["1080"] } }, ...numericValue["720"] && { 720: { type: "mp4", url: numericValue["720"] } }, ...numericValue["480"] && { 480: { type: "mp4", url: numericValue["480"] } }, ...numericValue["360"] && { 360: { type: "mp4", url: numericValue["360"] } }, ...numericValue.unknown && { unknown: { type: "mp4", url: numericValue.unknown } } },
        type: "file",
        flags: ["cors-allowed"]
    };
    return {
        embeds: [],
        stream: [stream]
    };
}
const ciaApiProviderConfig = {
    id: "cia-api",
    name: "CIA API (4K) \uD83D\uDD25",
    rank: 890,
    disabled: true,
    flags: ["cors-allowed"],
    scrapeMovie: scrapeCiaApiMovie
};
const ciaApiProvider = createSourceProvider(ciaApiProviderConfig);
const coitusBaseUrl = "https://api.coitus.ca";
async function scrapeCoitus(context) {
    const value = context.media.type === "movie" ? coitusBaseUrl + "/movie/" + context.media.tmdbId : coitusBaseUrl + "/tv/" + context.media.tmdbId + "/" + context.media.season.number + "/" + context.media.episode.number;
    const response = await context.proxiedFetcher(value);
    if (!response.videoSource) {
        throw new ScraperError("No watchable item found");
    }
    let videoSource2 = response.videoSource;
    let result = {};
    if (videoSource2.includes("orbitproxy")) {
        try {
            {
                const parts = videoSource2.split(/orbitproxy\.[^/]+\//);
                if (parts.length
                    >=
                        2) {
                    const parts2 = parts[1].split(".m3u8")[0];
                    try {
                        {
                            const value6 = Buffer.from(parts2, "base64").toString("utf-8");
                            const data = JSON.parse(value6);
                            const url = data.u;
                            const value7 = data.r || "";
                            const requestOptions = {
                                referer: value7
                            };
                            result = requestOptions;
                            videoSource2 =
                                buildProxiedHlsUrl(url, context.features, result);
                        }
                    }
                    catch (temporaryValue) {
                        console.error("Error decoding/parsing orbitproxy data:", temporaryValue);
                    }
                }
            }
        }
        catch (url2) {
            console.error("Error processing orbitproxy URL:", url2);
        }
    }
    console.log(response);
    context.progress(90);
    const stream = {
        id: "primary",
        captions: [],
        playlist: videoSource2,
        type: "hls",
        headers: result,
        flags: ["cors-allowed"]
    };
    return {
        embeds: [],
        stream: [stream]
    };
}
const coitusProviderConfig = {
    id: "coitus",
    name: "Cactus \uD83C\uDF35",
    rank: 91,
    disabled: true,
    flags: ["cors-allowed"],
    scrapeMovie: scrapeCoitus,
    scrapeShow: scrapeCoitus
};
const coitusProvider = createSourceProvider(coitusProviderConfig);
async function scrapeCuevana3(context) {
    const { tmdbId: tmdbId2, type: type2 } = context.media;
    if (!tmdbId2) {
        throw new ScraperError("TMDB ID is required");
    }
    const requestUrl = "https://ws-m3u8.moonpic.qzz.io:3008/tmdb";
    let value = "";
    if (type2 === "movie") {
        value = requestUrl + "/movie/" + tmdbId2;
    }
    else if (type2 === "show") {
        const media2 = context.media;
        if ((media2.season?.number)
            !=
                null
            &&
                (media2.episode?.number)
                    !=
                        null) {
            value = requestUrl + "/tv/" + tmdbId2 + "/season/" + media2.season.number + "/episode/" + media2.episode.number;
        }
        else {
            throw new ScraperError("Missing parameters for TV episode");
        }
    }
    else {
        throw new ScraperError("Missing parameters for TV episode");
    }
    const response = await fetch(value);
    if (!response.ok) {
        throw new ScraperError("Failed to fetch data from local server: " + response.statusText);
    }
    const data = await response.json();
    if (!data.embeds || !Array.isArray(data.embeds) ||
        data.embeds.length
            ===
                0) {
        throw new ScraperError("No valid streams found");
    }
    return {
        embeds: data.embeds
    };
}
const cuevana3ProviderConfig = {
    id: "cuevana3",
    name: "Cuevana3 \uD83D\uDEF5",
    rank: 80,
    disabled: true,
    flags: ["cors-allowed"],
    scrapeMovie: scrapeCuevana3,
    scrapeShow: scrapeCuevana3
};
const cuevana3Provider = createSourceProvider(cuevana3ProviderConfig);
async function embedsuDecodePayload(input) {
    const value = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/=";
    const normalizedValue = input.replace(/=+$/, "");
    let characterCode = "";
    if (normalizedValue.length % 4 === 1) {
        throw new Error("The string to be decoded is not correctly encoded.");
    }
    for (let value9 = 0, value10 = 0, value11 = 0; value11 <
        normalizedValue.length; value11++) {
        const value12 = normalizedValue.charAt(value11);
        const value13 = value.indexOf(value12);
        value13 ===
            -1
            || (value10 = value9 %
                4
                ?
                    value10 *
                        64 + value13
                : value13, value9++
                %
                    4
                && (characterCode += String.fromCharCode(255
                    & value10 >>
                        (-2
                            * value9
                            & 6))));
    }
    return characterCode;
}
async function scrapeEmbedsu(context) {
    const requestUrl = "https://embed.su/embed/" + (context.media.type === "movie" ? "movie/" + context.media.tmdbId : "tv/" + context.media.tmdbId + "/" + context.media.season.number + "/" + context.media.episode.number);
    const requestOptions = {
        Referer: "https://embed.su/",
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    };
    const requestOptions2 = {
        headers: requestOptions
    };
    const response = await context.proxiedFetcher(requestUrl, requestOptions2);
    const match = response.match(/window\.vConfig\s*=\s*JSON\.parse\(atob\(`([^`]+)/i);
    const value = match?.[1];
    if (!value) {
        throw new ScraperError("No encoded config found");
    }
    const data = JSON.parse(await embedsuDecodePayload(value));
    if (!(data != null && data.hash)) {
        throw new ScraperError("No stream hash found");
    }
    const items = (await embedsuDecodePayload(data.hash)).split(".").map(item => item.split("").reverse().join(""));
    const data3 = JSON.parse(await embedsuDecodePayload(items.join("").split("").reverse().join("")));
    if (!(data3 != null && data3.length)) {
        throw new ScraperError("No servers found");
    }
    context.progress(50);
    const items3 = data3.map(item => ({ embedId: "viper", url: "https://embed.su/api/e/" + item.hash }));
    context.progress(90);
    return {
        embeds: items3
    };
}
const embedsuProviderConfig = {
    id: "embedsu",
    name: "EmbedSu \uD83C\uDF7F",
    rank: 242,
    disabled: true,
    flags: [],
    scrapeMovie: scrapeEmbedsu,
    scrapeShow: scrapeEmbedsu
};
function fedapiProcessData() {
    try {
        if (typeof window === "undefined") {
            return null;
        }
        const value = window.localStorage.getItem("__MW::preferences");
        if (!value) {
            return null;
        }
        const data = JSON.parse(value);
        return (data?.state?.febboxKey) || null;
    }
    catch (temporaryValue3) {
        console.warn("Unable to access localStorage or parse auth data:", temporaryValue3);
        return null;
    }
}
function fedapiProcessData2() {
    try {
        if (typeof window === "undefined") {
            return null;
        }
        const value = window.localStorage.getItem("__MW::region");
        if (!value) {
            return null;
        }
        const data = JSON.parse(value);
        return (data?.state?.region) ?? null;
    }
    catch (temporaryValue3) {
        console.warn("Unable to access localStorage or parse auth data:", temporaryValue3);
        return null;
    }
}
const embedsuProvider = createSourceProvider(embedsuProviderConfig);
const fedapiBaseUrl = "https://fed-api2.pstream.mov";
const fedapiValue = ["east", "west", "south", "asia", "europe"];
function fedapiProcessData3(input) {
    const value = (input || "").toLowerCase();
    return fedapiValue.includes(value) ? value : "east";
}
async function scrapeFedapi(context) {
    var temporaryValue;
    const value = fedapiProcessData();
    if (!value) {
        throw new ScraperError("Requires a user token!");
    }
    const value10 = fedapiProcessData2();
    const url = context.media.type
        === "movie"
        ? fedapiBaseUrl + "/movie/" + context.media.tmdbId : fedapiBaseUrl + "/tv/" + context.media.tmdbId + "/" + context.media.season.number + "/" + context.media.episode.number;
    const response = await context.proxiedFetcher(url, { headers: { "ui-token": value, region: fedapiProcessData3(value10), Origin: "https://pstream.mov", Referer: "https://pstream.mov" } });
    if (response != null && response.error && response.error.startsWith("No results found in MovieBox search")) {
        throw new ScraperError("No stream found");
    }
    if ((response?.error) === "No cached data found for this episode") {
        throw new ScraperError("No stream found");
    }
    if ((response?.error)
        === "No cached data found for this ID") {
        throw new ScraperError("No stream found");
    }
    if (!response) {
        throw new ScraperError("No response from API");
    }
    context.progress(50);
    const numericValue = Object.entries(response.streams).reduce((accumulator, [S, k]) => {
        let value;
        return S
            === "ORG"
            ? (k.split("?")[0].toLowerCase().endsWith(".mp4") && (accumulator.unknown = k), accumulator) : (S === "4K" ? value = 2160 : value = parseInt(S.replace("P", ""), 10), Number.isNaN(value) || accumulator[value] || (accumulator[value] = k), accumulator);
    }, {});
    const value11 = Object.entries(numericValue).reduce((accumulator3, [S, k]) => {
        S
            !== "unknown"
            && (accumulator3[S] = k);
        return accumulator3;
    }, {});
    const captions = [];
    if (response.subtitles) {
        for (const [itemValue, itemValue2] of Object.entries(response.subtitles)) {
            const parts = itemValue.split("_")[0];
            const value12 = parts.charAt(0).toUpperCase()
                +
                    parts.slice(1);
            const language = ((temporaryValue =
                normalizeLanguageCode(value12)) == null ? void 0 : temporaryValue.toLowerCase()) ?? "unknown";
            if (itemValue2.subtitle_link) {
                const subtitle_link2 = itemValue2.subtitle_link;
                const normalizedValue = subtitle_link2.toLowerCase().endsWith(".vtt");
                const caption = {
                    type: normalizedValue ? "vtt" : "srt",
                    id: subtitle_link2,
                    url: subtitle_link2,
                    language: language,
                    hasCorsRestrictions: false
                };
                captions.push(caption);
            }
        }
    }
    context.progress(90);
    const stream = { ...value11[2160] && { "4k": { type: "mp4", url: value11[2160] } }, ...value11[1080] && { 1080: { type: "mp4", url: value11[1080] } }, ...value11[720] && { 720: { type: "mp4", url: value11[720] } }, ...value11[480] && { 480: { type: "mp4", url: value11[480] } }, ...value11[360] && { 360: { type: "mp4", url: value11[360] } }, ...value11.unknown && { unknown: { type: "mp4", url: value11.unknown } } };
    const stream3 = {
        id: "primary",
        captions: captions,
        qualities: stream,
        type: "file",
        flags: ["cors-allowed"]
    };
    return {
        embeds: [],
        stream: [stream3]
    };
}
const fedapiProviderConfig = {
    id: "fedapi",
    name: "FED API (4K) \uD83D\uDD25",
    rank: 892,
    disabled: true,
    flags: ["cors-allowed"],
    scrapeMovie: scrapeFedapi,
    scrapeShow: scrapeFedapi
};
const fedapiProvider = createSourceProvider(fedapiProviderConfig);
const filmekseniBaseUrl = "https://filmekseni.cc";
async function scrapeFilmekseni(context) {
    if (!context.media.imdbId) {
        throw new ScraperError("IMDb ID is required for this scraper");
    }
    const response = await context.proxiedFetcher("/search/", { baseUrl: filmekseniBaseUrl, method: "POST", body: new URLSearchParams({ query: context.media.imdbId }), headers: { "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8", "X-Requested-With": "XMLHttpRequest", Referer: filmekseniBaseUrl, Origin: filmekseniBaseUrl, "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/137.0.0.0 Safari/537.36", Accept: "application/json, text/javascript, */*; q=0.01", "Accept-Language": "en-US,en;q=0.9", "sec-ch-ua": "\"Google Chrome\";v=\"137\", \"Chromium\";v=\"137\", \"Not/A)Brand\";v=\"24\"", "sec-ch-ua-mobile": "?0", "sec-ch-ua-platform": "\"Windows\"", "Sec-Fetch-Dest": "empty", "Sec-Fetch-Mode": "cors", "Sec-Fetch-Site": "same-origin" } });
    const data = JSON.parse(response);
    if (!data.result ||
        data.result.length
            ===
                0) {
        throw new ScraperError("No search results found");
    }
    const value = data.result[0];
    const url = filmekseniBaseUrl + "/" + value.slug_prefix + value.slug + "/1";
    const response2 = await context.proxiedFetcher(url);
    const document = loadHtml(response2);
    const url3 = document(".card-video iframe").attr("data-src");
    if (!url3) {
        throw new ScraperError("No embed found");
    }
    return { embeds: [{ embedId: "vidmoly", url: url3.startsWith("https:") ? url3 : "https:" + url3 }] };
}
const filmekseniProviderConfig = {
    id: "filmekseni",
    name: "Ekseni \u2660\uFE0F(Turkish)",
    rank: 850,
    disabled: true,
    flags: ["cors-allowed"],
    scrapeMovie: scrapeFilmekseni,
    scrapeShow: scrapeFilmekseni
};
const filmekseniProvider = createSourceProvider(filmekseniProviderConfig);
const flickyBaseUrl = "https://uembed.site/api/videos/tmdb";
function flickyParseSources(input) {
    if (!(input != null && input.length)) {
        throw new ScraperError("Flicky: empty response");
    }
    const filteredItems = input.filter(item => item.status === "ready" && typeof item.file == "string");
    if (!filteredItems.length) {
        throw new ScraperError("Flicky: no playable sources");
    }
    return filteredItems;
}
function flickyProcessData(context) {
    if (!context.media.tmdbId) {
        throw new ScraperError("Flicky: missing TMDB id for movie");
    }
    return { id: String(context.media.tmdbId) };
}
function flickyNormalizeLanguage(input) {
    const value = Array.isArray(input?.tracks) ? input.tracks : [];
    if (!value.length) {
        return [];
    }
    const results = [];
    value.forEach((item, index) => {
        if (!(item != null && item.url)) {
            return;
        }
        const subtitleType = getSubtitleFileType(item.url)
            ?? "srt";
        let value3 = item.language ?? item.lang ?? item.label;
        if (typeof value3
            === "string") {
            const language = normalizeLanguageCode(value3)
                ?? value3.toLowerCase();
            if (isValidLanguageCode(language)) {
                value3 = language;
            }
            else {
                value3 = "unknown";
            }
        }
        else {
            value3 = "unknown";
        }
        const caption = {
            id: "flicky-" + index,
            url: item.url,
            type: subtitleType,
            language: value3,
            hasCorsRestrictions: false
        };
        results.push(caption);
    });
    return deduplicateCaptionsByLanguage(results);
}
function flickyMapCaptions(input, argument2) {
    if (!argument2.file) {
        throw new ScraperError("Flicky: missing stream URL");
    }
    return { embeds: [], stream: [{ id: "flicky-" + (argument2.id ?? "primary"), type: "hls", playlist: buildProxiedHlsUrl(argument2.file, input.features, { Referer: "https://uembed.site/", Origin: "https://uembed.site" }), headers: { Referer: "https://uembed.site/", Origin: "https://uembed.site" }, captions: flickyNormalizeLanguage(argument2), flags: ["cors-allowed"] }] };
}
async function scrapeFlickyMovie(context) {
    const response = await context.proxiedFetcher(flickyBaseUrl, { query: flickyProcessData(context) });
    const value = flickyParseSources(response);
    return flickyMapCaptions(context, value[0]);
}
const flickyProviderConfig = {
    id: "flicky",
    name: "Felicia \uD83D\uDCA7",
    rank: 860,
    disabled: true,
    flags: ["cors-allowed"],
    scrapeMovie: scrapeFlickyMovie
};
const flickyProvider = createSourceProvider(flickyProviderConfig);
const flipperBaseUrl = "https://vidfast.lordflix.club";
const flipperValue = ["neon", "sage", "cypher", "yoru", "reyna", "omen", "breach", "vyse", "killjoy", "harbor", "chamber", "fade", "gekko", "kayo", "raze", "phoenix", "astra"];
async function flipperBuildEmbeds(context) {
    const tmdbId2 = context.media.tmdbId;
    if (!tmdbId2) {
        throw new ScraperError("No TMDB ID found");
    }
    const results = [];
    for (const item of flipperValue) {
        const requestUrl = flipperBaseUrl + "/easy/movie/" + item + "/" + tmdbId2;
        const embed = {
            embedId: "flipper-" + item,
            url: requestUrl
        };
        results.push(embed);
    }
    return results;
}
async function flipperBuildEmbeds2(context) {
    const tmdbId2 = context.media.tmdbId;
    if (!tmdbId2) {
        throw new ScraperError("No TMDB ID found");
    }
    const number2 = context.media.season.number;
    const number3 = context.media.episode.number;
    const results = [];
    for (const item of flipperValue) {
        const requestUrl = flipperBaseUrl + "/easy/tv/" + item + "/" + tmdbId2 + "/" + number2 + "/" + number3;
        const embed = {
            embedId: "flipper-" + item,
            url: requestUrl
        };
        results.push(embed);
    }
    return results;
}
async function scrapeFlipperMovie(context) {
    return ({ embeds: await flipperBuildEmbeds(context) });
}
async function scrapeFlipperShow(context) {
    return ({ embeds: await flipperBuildEmbeds2(context) });
}
const flipperSourceProvider = createSourceProvider({ id: "flipper", name: "Easy (4K) \uD83D\uDC2C", rank: 875, disabled: true, flags: ["cors-allowed"], scrapeMovie: scrapeFlipperMovie, scrapeShow: scrapeFlipperShow });
const fullhdfilmizleBaseUrl = "https://www.fullhdfilmizlesene.tv";
const fullhdfilmizleValue = ["Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:128.0) Gecko/20100101 Firefox/128.0", "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"];
function fullhdfilmizleDecodePayload(input) {
    const value = ("" + input).replace(/[a-z]/gi, function (argument1) {
        return String.fromCharCode(argument1.charCodeAt(0) + (argument1.toLowerCase() < "n" ? 13 : -13));
    });
    return atob(value);
}
function fullhdfilmizleDecodePayload2(input) {
    const value = input.split("").reverse().join("");
    const characterCode = atob(value);
    let characterCode2 = "";
    for (let characterCode3 = 0; characterCode3 < characterCode.length; characterCode3 += 1) {
        const characterCode4 = "K9L"[characterCode3 %
            3];
        const characterCode5 = characterCode.charCodeAt(characterCode3)
            - (characterCode4.charCodeAt(0)
                %
                    5 +
                1);
        characterCode2 += String.fromCharCode(characterCode5);
    }
    return atob(characterCode2);
}
async function scrapeFullhdfilmizleMovie(context) {
    const imdbId2 = context.media.imdbId;
    if (!imdbId2) {
        throw new ScraperError("IMDB ID not found");
    }
    const value = fullhdfilmizleBaseUrl + "/arama/" + imdbId2;
    const requestOptions = {
        Referer: fullhdfilmizleBaseUrl,
        "User-Agent": fullhdfilmizleValue[0]
    };
    const requestOptions2 = {
        headers: requestOptions
    };
    const response = await context.proxiedFetcher(value, requestOptions2);
    const document = loadHtml(response);
    const url = document("a.tt").attr("href");
    if (!url) {
        throw new ScraperError("Could not find media link from search");
    }
    const requestOptions3 = {
        Referer: value,
        "User-Agent": fullhdfilmizleValue[0]
    };
    const requestOptions4 = {
        headers: requestOptions3
    };
    const response2 = await context.proxiedFetcher(url, requestOptions4);
    const document3 = loadHtml(response2);
    const value8 = document3("script:contains(\"var scx =\")").html();
    if (!value8) {
        throw new ScraperError("Could not find scx variable");
    }
    const match = value8.match(/var scx = (.*?);/);
    if (!match) {
        throw new ScraperError("Could not extract scx variable");
    }
    const data = JSON.parse(match[1]);
    const value9 = data.atom.sx.t;
    if (!value9 ||
        value9.length
            ===
                0) {
        throw new ScraperError("No sources found in scx data");
    }
    const value10 = fullhdfilmizleDecodePayload(value9[0]);
    for (const item of fullhdfilmizleValue)
        try {
            {
                const requestOptions5 = {
                    Accept: "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                    "Accept-Language": "en-US,en;q=0.5",
                    "Sec-Fetch-Dest": "iframe",
                    "Sec-Fetch-Mode": "navigate",
                    "Sec-Fetch-Site": "cross-site",
                    "User-Agent": item,
                    Referer: "https://www.fullhdfilmizlesene.tv/"
                };
                const requestOptions6 = {
                    headers: requestOptions5
                };
                const response3 = await context.proxiedFetcher(value10, requestOptions6);
                const match6 = response3.match(/"file": av\('(.*?)'\)/);
                if (!match6) {
                    throw new ScraperError("Could not find encoded stream URL");
                }
                const value11 = match6[1];
                const value12 = fullhdfilmizleDecodePayload2(value11);
                const captions = [];
                const match7 = response3.match(/jwSetup\.tracks = (\[.*?\]);/s);
                if (match7) {
                    try {
                        const data3 = JSON.parse(match7[1]);
                        for (const temporaryValue4 of data3) {
                            if (temporaryValue4.kind
                                !==
                                    "captions") {
                                continue;
                            }
                            let value13 = null;
                            if (/tur/i.test(temporaryValue4.label) || /tur/i.test(temporaryValue4.file)) {
                                value13 = "tr";
                            }
                            else if (/eng/i.test(temporaryValue4.label) || /eng/i.test(temporaryValue4.file)) {
                                value13 = "en";
                            }
                            if (!value13) {
                                continue;
                            }
                            const caption = {
                                id: temporaryValue4.file,
                                url: temporaryValue4.file,
                                type: "vtt",
                                language: value13,
                                hasCorsRestrictions: false
                            };
                            captions.push(caption);
                        }
                    }
                    catch {
                    }
                }
                const stream = {
                    id: "primary",
                    type: "hls",
                    playlist: value12,
                    flags: ["cors-allowed"],
                    captions: captions
                };
                return {
                    embeds: [],
                    stream: [stream]
                };
            }
        }
        catch (temporaryValue5) {
            if (temporaryValue5 instanceof ScraperError) {
                continue;
            }
            throw temporaryValue5;
        }
    throw new ScraperError("Could not find encoded stream URL");
}
const fullhdfilmizleProviderConfig = {
    id: "fullhdfilmizle",
    name: "ALTR \uD83D\uDD35(Turkish)",
    rank: 840,
    disabled: true,
    flags: ["cors-allowed"],
    scrapeMovie: scrapeFullhdfilmizleMovie
};
const fullhdfilmizleProvider = createSourceProvider(fullhdfilmizleProviderConfig);
function fullhdfilmizleSelectServer() {
    const value = () => Math.floor(Math.random() * 16).toString(16);
    const value3 = argument1 => Array.from({ length: argument1 }, value).join("");
    return value3(8) + "-" + value3(4) + "-" + value3(4) + "-" + value3(4) + "-" + value3(12);
}
function fullhdfilmizleNormalizeLanguage(input) {
    if (!input || typeof input === "boolean") {
        return [];
    }
    const value = input.split(",");
    const results = [];
    value.forEach(item => {
        const match = item.match(/\[([^\]]+)\](https?:\/\/\S+?)(?=,\[|$)/);
        if (match) {
            const subtitleType = getSubtitleFileType(match[2]);
            const language = normalizeLanguageCode(match[1]);
            if (!subtitleType || !language) {
                return;
            }
            const caption = {
                id: match[2],
                language: language,
                hasCorsRestrictions: false,
                type: subtitleType,
                url: match[2]
            };
            results.push(caption);
        }
    });
    return results;
}
function hdrezkaMapQuality(input) {
    if (!input) {
        throw new ScraperError("No video links found");
    }
    try {
        const result = {};
        input.split(",").forEach(item => {
            const match = item.match(/\[([^\]]+)\](https?:\/\/[^\s,]+)/);
            if (match) {
                const [itemValue, itemValue2, itemValue3] = match;
                if (itemValue3 ===
                    "null") {
                    return;
                }
                const normalizedValue = itemValue2.replace(/<[^>]+>/g, "").toLowerCase().replace("p", "").trim();
                result[normalizedValue] = { type: "mp4", url: itemValue3.trim() };
            }
        });
        const result2 = {};
        Object.entries(result).forEach(([f, i]) => {
            ;
            {
                const value = fsharetvMapQuality(f);
                const value2 = value === "unknown"
                    ? "1080" : value;
                if (!result2[value2]) {
                    (result2[value2] = i);
                }
            }
        });
        return result2;
    }
    catch (temporaryValue) {
        throw console.error("Error parsing video links:", temporaryValue), new ScraperError("Failed to parse video links");
    }
}
const hdrezkaBaseUrl = "https://hdrezka.ag/";
const hdrezkaValue = {
    "X-Hdrezka-Android-App": "1",
    "X-Hdrezka-Android-App-Version": "2.2.0",
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36",
    "Accept-Language": "ru-RU,ru;q=0.9,en-US;q=0.8,en;q=0.7",
    "CF-IPCountry": "RU"
};
const hdrezkaValue2 = hdrezkaValue;
async function hdrezkaGetFileExtension(context) {
    const response = await context.proxiedFetcher("/engine/ajax/search.php", { baseUrl: hdrezkaBaseUrl, headers: hdrezkaValue2, query: { q: context.media.title } });
    const document = loadHtml(response);
    const match = document("a").map((item, index) => {
        const value2 = document(index);
        const url = value2.attr("href");
        const match = value2.find("span.enty").text();
        const match4 = match.match(/\((\d{4})\)/) || (url == null ? void 0 : url.match(/-(\d{4})(?:-|\.html)/)) || match.match(/(\d{4})/);
        const value3 = match4 ? match4[1] : null;
        const match5 = (url == null ? void 0 : url.match(/\/(\d+)-[^/]+\.html$/))?.[1];
        return match5 ? { id: match5, year: value3 ? parseInt(value3, 10) : context.media.releaseYear, type: context.media.type, url: url || "" } : null;
    }).get().filter(Boolean);
    match.sort((left, right) => {
        const result = { QaWmD: function (argument1, argument2) {
                return argument1(argument2);
            }, AfzHC: "srt" };
        {
            const value = Math.abs(left.year
                -
                    context.media.releaseYear);
            const value2 = Math.abs(right.year
                -
                    context.media.releaseYear);
            return value - value2;
        }
    });
    return match[0] || null;
}
async function hdrezkaResolveStream(context, argument2, argument3) {
    const queryParams = new URLSearchParams;
    queryParams.append("id", context);
    queryParams.append("translator_id", argument2);
    argument3.media.type === "show" && (queryParams.append("season", argument3.media.season.number.toString()), queryParams.append("episode", argument3.media.episode.number.toString()));
    queryParams.append("favs", fullhdfilmizleSelectServer());
    queryParams.append("action", argument3.media.type === "show" ? "get_stream" : "get_movie");
    queryParams.append("t", Date.now().toString());
    const response = await argument3.proxiedFetcher("/ajax/get_cdn_series/", { baseUrl: hdrezkaBaseUrl, method: "POST", body: queryParams, headers: { ...hdrezkaValue2, "Content-Type": "application/x-www-form-urlencoded", "X-Requested-With": "XMLHttpRequest", Referer: hdrezkaBaseUrl + "films/action/" + context + "-novokain-2025-latest.html" } });
    try {
        {
            const data = JSON.parse(response);
            if (!data.url && data.success) {
                throw new ScraperError("Movie found but no stream available (might be premium or not yet released)");
            }
            if (!data.url) {
                throw new ScraperError("No stream URL found in response");
            }
            return data;
        }
    }
    catch (temporaryValue) {
        throw console.error("Error parsing stream response:", temporaryValue), new ScraperError("Failed to parse stream response");
    }
}
async function hdrezkaExtractValue(context, argument2, argument3) {
    const requestOptions = {
        headers: hdrezkaValue2
    };
    const response = await argument3.proxiedFetcher(context, requestOptions);
    if (response.includes("data-translator_id=\"238\"")) {
        return "238";
    }
    const value = argument3.media.type
        ===
            "movie"
        ? "initCDNMoviesEvents" : "initCDNSeriesEvents";
    const value3 = new RegExp("sof\\.tv\\." + value + "\\(" + argument2 + ", ([^,]+)", "i");
    const match = response.match(value3);
    return match ? match[1] : null;
}
async function scrapeHdrezka(context) {
    const value = await hdrezkaGetFileExtension(context);
    if (!value || !value.id) {
        throw new ScraperError("No result found");
    }
    const extractedKey = await hdrezkaExtractValue(value.url, value.id, context);
    if (!extractedKey) {
        throw new ScraperError("No translator id found");
    }
    const { url: url, subtitle: subtitle2 } = await hdrezkaResolveStream(value.id, extractedKey, context);
    const value4 = hdrezkaMapQuality(url);
    const value5 = fullhdfilmizleNormalizeLanguage(subtitle2);
    context.progress(90);
    const stream = {
        id: "primary",
        type: "file",
        flags: ["cors-allowed", "ip-locked"],
        captions: value5,
        qualities: value4
    };
    return {
        embeds: [],
        stream: [stream]
    };
}
const hdrezkaProviderConfig = {
    id: "hdrezka",
    name: "HDRezka \uD83E\uDEBC",
    rank: 870,
    flags: ["cors-allowed", "ip-locked"],
    scrapeShow: scrapeHdrezka,
    scrapeMovie: scrapeHdrezka
};
const hdrezkaProvider = createSourceProvider(hdrezkaProviderConfig);
async function hollymoviehdDecodePayload(input, argument2, argument3) {
    const requestOptions = {
        headers: argument3
    };
    const value = await input(argument2, requestOptions);
    const value3 = st.parse(value);
    if (value3.isMasterPlaylist) {
        const parsedUrl = new URL(argument2).origin;
        await Promise.all(value3.variants.map(async (item) => {
            ;
            {
                let url = item.uri;
                if (!url.startsWith("http")) {
                    (!url.startsWith("/") && (url = "/" + url), url = parsedUrl + url);
                }
                const requestOptions = {
                    headers: argument3
                };
                const value = await input(url, requestOptions);
                const value5 = st.parse(value);
                item.uri = "data:application/vnd.apple.mpegurl;base64," +
                    btoa(st.stringify(value5));
            }
        }));
    }
    return "data:application/vnd.apple.mpegurl;base64," + btoa(st.stringify(value3));
}
const hollymoviehdValue = atob("c3VwZXJzZWNyZXRrZXk=");
const hollymoviehdBaseUrl = "https://reyna.bludclart.com/api/source/hollymoviehd";
function hollymoviehdCreateToken(input, argument2 = "", argument3 = "") {
    const value = input + ":" + argument2 + ":" + argument3;
    return CryptoJS.HmacSHA256(value, hollymoviehdValue).toString(CryptoJS.enc.Hex);
}
async function scrapeHollymoviehd(context) {
    let value = hollymoviehdBaseUrl + "/" + context.media.tmdbId;
    let value6 = "";
    let value7 = "";
    if (context.media.type === "show") {
        (value6 = context.media.season.number.toString(), value7 = context.media.episode.number.toString(), value += "/" + value6 + "/" + value7);
    }
    const value8 = hollymoviehdCreateToken(context.media.tmdbId, value6, value7);
    value += "?vrf=" + value8;
    const response = await context.proxiedFetcher(value);
    const value9 = response?.sources?.[0]?.file;
    if (!value9) {
        throw new ScraperError("Sources not found.");
    }
    context.progress(50);
    context.progress(90);
    return { embeds: [], stream: [{ id: "primary", type: "hls", playlist: await hollymoviehdDecodePayload(context.proxiedFetcher, value9), proxyDepth: 2, flags: ["cors-allowed"], captions: [] }] };
}
const hollymoviehdProviderConfig = {
    id: "hollymoviehd",
    name: "HollyMovieHD \uD83E\uDD42",
    rank: 180,
    disabled: true,
    flags: ["cors-allowed"],
    scrapeMovie: scrapeHollymoviehd,
    scrapeShow: scrapeHollymoviehd
};
const hollymoviehdProvider = createSourceProvider(hollymoviehdProviderConfig);
function iosmirrorProcessData(input) {
    return Object.entries(input).map(([_, c]) => n7.serialize(_, c)).join("; ");
}
async function scrapeIosmirror(context) {
    const response = decodeURIComponent(await context.fetcher("https://iosmirror-hash.pstream.org/"));
    if (!response) {
        throw new ScraperError("No hash found");
    }
    context.progress(10);
    const result = {
        t_hash_t: response,
        hd: "on"
    };
    const searchResponse = await context.proxiedFetcher("/search.php", { baseUrl: iosmirrorBaseUrl2, query: { s: context.media.title }, headers: { cookie: iosmirrorProcessData(result) } });
    if (searchResponse.status
        !==
            "y"
        || !searchResponse.searchResult) {
        throw new ScraperError(searchResponse.error);
    }
    async function fetchItemDetails(item) {
        const result = {
            id: item
        };
        const result3 = {
            t_hash_t: response,
            hd: "on"
        };
        return context.proxiedFetcher("/post.php", { baseUrl: iosmirrorBaseUrl2, query: result, headers: { cookie: iosmirrorProcessData(result3) } });
    }
    context.progress(30);
    let temporaryValue11;
    let item = searchResponse.searchResult.find(async (item) => {
        return (temporaryValue11 = await fetchItemDetails(item.id), fsharetvProcessData(item.t, context.media.title)
            && (Number(temporaryValue11.year) ===
                context.media.releaseYear
                ||
                    temporaryValue11.type
                        ===
                            (context.media.type
                                === "movie"
                                ? "m" : "t")));
    })?.id;
    if (!item) {
        throw new ScraperError("No watchable item found");
    }
    if (context.media.type === "show") {
        temporaryValue11 = await fetchItemDetails(item);
        const media2 = context.media;
        const match = (temporaryValue11 == null ? void 0 : temporaryValue11.season.find(item => Number(item.s) === media2.season.number))?.id;
        if (!match) {
            throw new ScraperError("Season not available");
        }
        const result2 = {
            s: match,
            series: item
        };
        const result3 = {
            t_hash_t: response,
            hd: "on"
        };
        const response2 = await context.proxiedFetcher("/episodes.php", { baseUrl: iosmirrorBaseUrl2, query: result2, headers: { cookie: iosmirrorProcessData(result3) } });
        let captions = [...response2.episodes];
        let value = 2;
        for (; response2.nextPageShow
            ===
                1;) {
            const result4 = {
                t_hash_t: response,
                hd: "on"
            };
            const response3 = await context.proxiedFetcher("/episodes.php", { baseUrl: iosmirrorBaseUrl2, query: { s: match, series: item, page: value.toString() }, headers: { cookie: iosmirrorProcessData(result4) } });
            captions = [...captions, ...response3.episodes];
            response2.nextPageShow = response3.nextPageShow;
            value++;
        }
        const match2 = captions.find(item => item.ep === "E" + media2.episode.number && item.s === "S" + media2.season.number)?.id;
        if (!match2) {
            throw new ScraperError("Episode not available");
        }
        item = match2;
    }
    const result5 = {
        id: item
    };
    const result6 = {
        t_hash_t: response,
        hd: "on"
    };
    const playlistResponse = await context.proxiedFetcher("/playlist.php?", { baseUrl: iosmirrorBaseUrl2, query: result5, headers: { cookie: iosmirrorProcessData(result6) } });
    context.progress(50);
    let match3 = playlistResponse[0].sources.find(item => item.label === "Auto")?.file;
    if (!match3) {
        match3 = playlistResponse[0].sources.find(item => item.label === "Full HD")?.file;
    }
    if (!match3 && (console.log("\"Full HD\" or \"Auto\" file not found, falling back to first source"), match3 = playlistResponse[0].sources[0].file), !match3) {
        throw new Error("Failed to fetch playlist");
    }
    const result7 = {
        hd: "on"
    };
    const requestOptions = { referer: iosmirrorBaseUrl, cookie: iosmirrorProcessData(result7) };
    const playlistUrl = buildProxiedHlsUrl("" + iosmirrorBaseUrl + match3, context.features, requestOptions);
    context.progress(90);
    const stream = {
        id: "primary",
        playlist: playlistUrl,
        type: "hls",
        headers: requestOptions,
        flags: ["cors-allowed"],
        captions: []
    };
    return {
        embeds: [],
        stream: [stream]
    };
}
const iosmirrorBaseUrl = "https://iosmirror.cc";
const iosmirrorBaseUrl2 = "https://m3u8-proxy-orcin.vercel.app/";
const iosmirrorProviderConfig = {
    id: "iosmirror",
    name: "NetMirror",
    rank: 182,
    disabled: true,
    flags: ["cors-allowed"],
    scrapeMovie: scrapeIosmirror,
    scrapeShow: scrapeIosmirror
};
async function scrapeIosmirrorpv(context) {
    const response = decodeURIComponent(await context.fetcher("https://iosmirror-hash.pstream.org/"));
    if (!response) {
        throw new ScraperError("No hash found");
    }
    context.progress(10);
    const result = {
        t_hash_t: response,
        hd: "on"
    };
    const searchResponse = await context.proxiedFetcher("/search.php", { baseUrl: iosmirrorpvBaseUrl2, query: { s: context.media.title }, headers: { cookie: iosmirrorProcessData(result) } });
    if (!searchResponse.searchResult) {
        throw new ScraperError(searchResponse.error);
    }
    async function fetchItemDetails(item) {
        {
            const result = {
                id: item
            };
            const result3 = {
                t_hash_t: response,
                hd: "on"
            };
            return context.proxiedFetcher("/post.php", { baseUrl: iosmirrorpvBaseUrl2, query: result, headers: { cookie: iosmirrorProcessData(result3) } });
        }
    }
    context.progress(30);
    let item = searchResponse.searchResult.find(async (item) => {
        const value = await fetchItemDetails(item.id);
        return fsharetvProcessData(item.t, context.media.title)
            && (Number(item.y)
                ===
                    context.media.releaseYear
                ||
                    value.type
                        ===
                            (context.media.type
                                ===
                                    "movie"
                                ? "m" : "t"));
    })?.id;
    if (!item) {
        throw new ScraperError("No watchable item found");
    }
    if (context.media.type
        === "show") {
        const value = await fetchItemDetails(item);
        const media2 = context.media;
        const match = (value == null ? void 0 : value.season.find(item => Number(item.s) === media2.season.number))?.id;
        if (!match) {
            throw new ScraperError("Season not available");
        }
        const result2 = {
            s: match,
            series: item
        };
        const result3 = {
            t_hash_t: response,
            hd: "on"
        };
        const response2 = await context.proxiedFetcher("/episodes.php", { baseUrl: iosmirrorpvBaseUrl2, query: result2, headers: { cookie: iosmirrorProcessData(result3) } });
        let captions = [...response2.episodes];
        let value3 = 2;
        for (; response2.nextPageShow
            ===
                1;) {
            const result4 = {
                t_hash_t: response,
                hd: "on"
            };
            const response3 = await context.proxiedFetcher("/episodes.php", { baseUrl: iosmirrorpvBaseUrl2, query: { s: match, series: item, page: value3.toString() }, headers: { cookie: iosmirrorProcessData(result4) } });
            captions = [...captions, ...response3.episodes];
            response2.nextPageShow = response3.nextPageShow;
            value3++;
        }
        const match2 = captions.find(item => item.ep === "E" + media2.episode.number && item.s === "S" + media2.season.number)?.id;
        if (!match2) {
            throw new ScraperError("Episode not available");
        }
        item = match2;
    }
    const result5 = {
        id: item
    };
    const result6 = {
        t_hash_t: response,
        hd: "on"
    };
    const playlistResponse = await context.proxiedFetcher("/playlist.php?", { baseUrl: iosmirrorpvBaseUrl2, query: result5, headers: { cookie: iosmirrorProcessData(result6) } });
    context.progress(50);
    let match3 = playlistResponse[0].sources.find(item => item.label === "Auto")?.file;
    if (!match3 && (match3 = playlistResponse[0].sources.find(item => item.label === "Full HD")?.file), !match3 && (console.log("\"Full HD\" or \"Auto\" file not found, falling back to first source"), match3 = playlistResponse[0].sources[0].file), !match3) {
        throw new Error("Failed to fetch playlist");
    }
    const result7 = {
        hd: "on"
    };
    const requestOptions = { referer: iosmirrorpvBaseUrl, cookie: iosmirrorProcessData(result7) };
    const playlistUrl = buildProxiedHlsUrl("" + iosmirrorpvBaseUrl + match3, context.features, requestOptions);
    context.progress(90);
    const stream = {
        id: "primary",
        playlist: playlistUrl,
        type: "hls",
        headers: requestOptions,
        flags: ["cors-allowed"],
        captions: []
    };
    return {
        embeds: [],
        stream: [stream]
    };
}
const iosmirrorProvider = createSourceProvider(iosmirrorProviderConfig);
const iosmirrorpvBaseUrl = "https://iosmirror.cc";
const iosmirrorpvBaseUrl2 = "https://vercel-sucks.up.railway.app/iosmirror.cc:443/pv";
const iosmirrorpvProviderConfig = {
    id: "iosmirrorpv",
    name: "PrimeMirror",
    rank: 183,
    disabled: true,
    flags: ["cors-allowed"],
    scrapeMovie: scrapeIosmirrorpv,
    scrapeShow: scrapeIosmirrorpv
};
const iosmirrorpvProvider = createSourceProvider(iosmirrorpvProviderConfig);
async function lookmovieResolveStream(context, argument2, argument3) {
    let value = "";
    argument3.type === "show" ? value = "/v1/episodes/view" : argument3.type === "movie" && (value = "/v1/movies/view");
    const result = {
        expand: "streams,subtitles",
        id: argument2
    };
    const requestOptions = {
        baseUrl: lookmovieBaseUrl,
        query: result
    };
    return await context.proxiedFetcher(value, requestOptions);
}
async function lookmovieNormalizeLanguage(input, language, language3) {
    const value = await lookmovieResolveStream(input, language, language3);
    const streams2 = value.streams;
    const captions = ["auto", "1080p", "1080", "720p", "720", "480p", "480", "240p", "240", "360p", "360", "144", "144p"];
    let value3 = null;
    for (const item of captions)
        if (streams2[item] && !value3) {
            value3 = streams2[item];
        }
    let captions3 = [];
    for (const track of value.subtitles) {
        const language5 = normalizeLanguageCode(track.language);
        if (!language5) {
            continue;
        }
        const stream = {
            id: track.url,
            type: "vtt",
            url: "" + lookmovieBaseUrl + track.url,
            hasCorsRestrictions: false,
            language: language5
        };
        captions3.push(stream);
    }
    captions3 =
        deduplicateCaptionsByLanguage(captions3);
    return {
        playlist: value3,
        captions: captions3
    };
}
const lookmovieBaseUrl = "https://lmscript.xyz";
async function lookmovieParseHtml(context, argument2) {
    if (argument2.type === "show") {
        const result = {
            "filters[q]": argument2.title
        };
        const requestOptions = {
            baseUrl: lookmovieBaseUrl,
            query: result
        };
        return (await context.proxiedFetcher("/v1/shows", requestOptions)).items.find(item => fsharetvProcessData2(argument2, item.title, Number(item.year)));
    }
    if (argument2.type
        ===
            "movie") {
        const result2 = {
            "filters[q]": argument2.title
        };
        const requestOptions2 = {
            baseUrl: lookmovieBaseUrl,
            query: result2
        };
        return (await context.proxiedFetcher("/v1/movies", requestOptions2)).items.find(item => fsharetvProcessData2(argument2, item.title, Number(item.year)));
    }
}
async function lookmovieParseHtml2(context, media, argument3) {
    var temporaryValue;
    let value = null;
    if (media.type === "movie") {
        value = argument3.id_movie;
    }
    else if (media.type
        === "show") {
        const result = {
            expand: "episodes",
            id: argument3.id_show
        };
        const requestOptions = {
            baseUrl: lookmovieBaseUrl,
            query: result
        };
        const response = await context.proxiedFetcher("/v1/shows", requestOptions);
        const item = (temporaryValue = response.episodes) == null ? void 0 : temporaryValue.find(item => {
            return Number(item.season)
                ===
                    Number(media.season.number)
                &&
                    Number(item.episode)
                        === Number(media.episode.number);
        });
        if (item) {
            (value = item.id);
        }
    }
    if (value ===
        null) {
        throw new ScraperError("Not found");
    }
    return await lookmovieNormalizeLanguage(context, value, media);
}
async function scrapeLookmovie(context) {
    const value = await lookmovieParseHtml(context, context.media);
    if (!value) {
        throw new ScraperError("Media not found");
    }
    context.progress(30);
    const value3 = await lookmovieParseHtml2(context, context.media, value);
    if (!value3.playlist) {
        throw new ScraperError("No video found");
    }
    context.progress(60);
    const stream = {
        id: "primary",
        playlist: value3.playlist,
        type: "hls",
        flags: ["ip-locked"],
        captions: value3.captions
    };
    return {
        embeds: [],
        stream: [stream]
    };
}
const lookmovieProviderConfig = {
    id: "lookmovie",
    name: "LookMovie \uD83D\uDEDD",
    disabled: false,
    rank: 60,
    flags: ["ip-locked"],
    scrapeShow: scrapeLookmovie,
    scrapeMovie: scrapeLookmovie
};
const lookmovieProvider = createSourceProvider(lookmovieProviderConfig);
async function scrapeMadplay(context) {
    const value = { type: context.media.type, title: context.media.title, tmdbId: context.media.tmdbId, imdbId: context.media.imdbId, ...context.media.type === "show" && { season: context.media.season.number, episode: context.media.episode.number } };
    value.releaseYear = context.media.releaseYear;
    const value3 = value;
    return { embeds: [{ embedId: "madplay-base", url: JSON.stringify(value3) }, { embedId: "madplay-nsapi", url: JSON.stringify(value3) }, { embedId: "madplay-roper", url: JSON.stringify(value3) }, { embedId: "madplay-vidfast", url: JSON.stringify(value3) }] };
}
const madplayProviderConfig = {
    id: "madplay",
    name: "Flicky \uD83C\uDF7F",
    rank: 860,
    disabled: true,
    flags: ["cors-allowed"],
    scrapeMovie: scrapeMadplay,
    scrapeShow: scrapeMadplay
};
const madplayProvider = createSourceProvider(madplayProviderConfig);
const mappletvBaseUrl = "https://mapple.uk";
async function scrapeMappletv(context) {
    const type2 = context.media.type;
    const tmdbId2 = context.media.tmdbId;
    let value = "";
    let captions = [];
    type2 === "movie"
        ? (value = mappletvBaseUrl + "/watch/movie/" + tmdbId2 + "?autoPlay=false", captions = [{ mediaId: Number(tmdbId2), mediaType: "movie", tv_slug: "" }]) : (value = mappletvBaseUrl + "/watch/tv/" + tmdbId2 + "-" + context.media.season.number + "/" + context.media.episode.number + "?autoPlay=false&autoNext=false", captions = [{ mediaId: Number(tmdbId2), mediaType: "tv", tv_slug: context.media.season.number + "-" + context.media.episode.number }]);
    const response = (await context.proxiedFetcher(value, { method: "POST", headers: { Accept: "text/x-component", "Accept-Encoding": "gzip, deflate, br, zstd", "Accept-Language": "en-US,en;q=0.5", Connection: "keep-alive", "Content-Type": "text/plain;charset=UTF-8", Host: "mapple.uk", "Next-Action": "403f7ef15810cd565978d2ac5b7815bb0ff20258a5", "Next-Router-State-Tree": "%5B%22%22%2C%7B%22children%22%3A%5B%22watch%22%2C%7B%22children%22%3A%5B%22movie%22%2C%7B%22children%22%3A%5B%5B%22id%22%2C%22557%22%2C%22d%22%5D%2C%7B%22children%22%3A%5B%22__PAGE__%3F%7B%5C%22autoPlay%5C%22%3A%5C%22false%5C%22%7D%22%2C%7B%7D%2C%22%2Fwatch%2Fmovie%2F557%3FautoPlay%3Dfalse%22%2C%22refresh%22%5D%7D%5D%7D%5D%7D%5D%7D%2Cnull%2Cnull%2Ctrue%5D", Origin: "https://mapple.uk", Priority: "u=4", Referer: "https://mapple.uk/", "Sec-Fetch-Dest": "empty", "Sec-Fetch-Mode": "cors", "Sec-Fetch-Site": "same-origin", "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:142.0) Gecko/20100101 Firefox/142.0" }, body: JSON.stringify(captions) })).split(`
`).find(item => item.startsWith("1:"));
    if (!response) {
        throw new ScraperError("Could not find stream data in response");
    }
    const data = JSON.parse(response.substring(2));
    if (!data.success || !data.data.stream_url) {
        throw new ScraperError("Stream data indicates failure or is missing URL");
    }
    const stream_url2 = data.data.stream_url;
    return { stream: [{ id: "primary", type: "hls", playlist: buildProxiedHlsUrl(stream_url2, context.features, { Origin: "https://mapple.uk", Referer: "https://mapple.uk/" }), headers: { Origin: "https://mapple.uk", Referer: "https://mapple.uk/" }, flags: ["cors-allowed"], captions: [] }], embeds: [] };
}
const mappletvProviderConfig = {
    id: "mappletv",
    name: "Mapple \uD83C\uDF43",
    rank: 885,
    disabled: true,
    flags: ["cors-allowed"],
    scrapeMovie: scrapeMappletv,
    scrapeShow: scrapeMappletv
};
const mappletvProvider = createSourceProvider(mappletvProviderConfig);
const modocineBaseUrl = "https://play.modocine.com";
const modocineBaseUrl2 = "https://fembox.lordflix.club/modocine";
async function scrapeModocine(context) {
    var url;
    const tmdbId2 = context.media.tmdbId;
    let url2;
    context.media.type === "movie" ? url2 = modocineBaseUrl + "/play.php/embed/movie/" + tmdbId2 + "?api=1" : url2 = modocineBaseUrl + "/play.php/embed/tv/" + tmdbId2 + "/" + context.media.season.number + "/" + context.media.episode.number + "?api=1";
    const requestOptions = {
        Referer: modocineBaseUrl
    };
    const requestOptions2 = {
        headers: requestOptions
    };
    const response = await context.proxiedFetcher(url2, requestOptions2);
    if (!(response != null && response.success) || !((url = response.data?.[0]) != null && url.embed_url)) {
        throw new ScraperError("Failed to retrieve embed URL from modocine");
    }
    const embed_url2 = response.data[0].embed_url;
    const match = embed_url2.match(/\/embed\/([a-zA-Z0-9]+)$/);
    if (!match) {
        throw new ScraperError("Failed to extract embed ID from URL");
    }
    const value = match[1];
    const response2 = await context.fetcher(modocineBaseUrl2 + "/" + value);
    if (!(response2 != null && response2.success) || !response2.streamUrl) {
        throw new ScraperError("Failed to retrieve stream URL from fembox API");
    }
    const streamUrl2 = response2.streamUrl;
    const playlistUrl = buildProxiedHlsUrl(streamUrl2, context.features, {});
    const stream = {
        id: "primary",
        playlist: playlistUrl,
        type: "hls",
        flags: ["cors-allowed"],
        captions: [],
        headers: {}
    };
    return {
        embeds: [],
        stream: [stream]
    };
}
const modocineProviderConfig = {
    id: "modocine",
    name: "ModoCine (Spanish)",
    rank: 802,
    disabled: true,
    flags: ["cors-allowed"],
    scrapeMovie: scrapeModocine,
    scrapeShow: scrapeModocine
};
const modocineProvider = createSourceProvider(modocineProviderConfig);
const modocineValue = "limon87";
const modocineBaseUrl3 = "https://gem.aether.mom/v1beta/models/gemini-2.5-flash-lite:generateContent";
function modocineProcessData(media, key, key2) {
    const value = media.season.number > 1 ? " and has " + media.season.number + " seasons" : "";
    const value3 = key2 ? " (AniList English title: \"" + key2 + '")' : "";
    return ("\n    You are an AI that matches TMDB movie and show data to myanime search results.\n    The user is searching for \"" + media.title + '"' + value3 + " which was released in " + media.releaseYear + value + ".\n    The user is looking for season " + media.season.number + " (TMDB title: \"" + media.season.title + "\", " + (media.season.episodeCount ?? "unknown") + " episodes), episode " + media.episode.number + ".\n\n    Here are the search results from myanime:\n    " + JSON.stringify(key, null, 2) + "\n\n    IMPORTANT: Some shows on TMDB have continuous episode numbering across seasons (e.g., episode 25 is the first episode of season 2), but myanime lists seasons as separate entries with their own episode counts. The myanime entry may also have a different title (e.g., \"Mugen Train Arc\").\n    To solve this, please return a JSON object with a \"results\" array that contains ALL entries from the search results that match the requested show, including all of its seasons, even if the user is only asking for one.\n    Each object in the \"results\" array should have the \"id\" of the matching anime from the myanime search results, and the \"season\" number. You must determine the season number for each entry based on its title.\n    The results MUST be sorted by season number in ascending order so the calling code can correctly map the episode number.\n    Pay close attention to the season title and episode counts from both TMDB and the myanime results to find the best match. If TMDB combines seasons into one, you must split them based on the episode counts in the search results.\n    Use the TMDB season title as the primary key for matching, and do not assign the same season number to different arcs.\n    Your response must only be the raw JSON object, without any markdown formatting, comments, or other text.\n  ").trim();
}
async function myanimeFetchData(context, key, key2, key3) {
    try {
        const value = modocineProcessData(key, key2, key3);
        const result = {
            text: value
        };
        const result2 = {
            parts: [result]
        };
        const result3 = {
            contents: [result2]
        };
        const response = await context.fetcher(modocineBaseUrl3, { method: "POST", headers: { "Content-Type": "application/json", "x-goog-api-key": modocineValue }, body: JSON.stringify(result3) });
        const text2 = response.candidates[0].content.parts[0].text;
        const value5 = text2.indexOf("{");
        const value6 = text2.lastIndexOf("}");
        if (value5 === -1 ||
            value6 ===
                -1) {
            throw new Error("Invalid AI response: No JSON object found");
        }
        const value7 = text2.substring(value5, value6 +
            1);
        const data = JSON.parse(value7);
        if (!data.results || !Array.isArray(data.results)) {
            throw new Error("Invalid AI response format");
        }
        return data;
    }
    catch (temporaryValue) {
        temporaryValue instanceof Error && context.progress(0);
        return null;
    }
}
async function scrapeMyanimeShow(context) {
    var temporaryValue;
    var temporaryValue6;
    var temporaryValue7;
    const value = await hianimeFetchData(context, context.media);
    const results5 = [];
    const value6 = value ? [context.media.title, value] : [context.media.title];
    for (const item of value6)
        try {
            const response = await context.proxiedFetcher("https://myanime.aether.mom/api/search?keyword=" +
                encodeURIComponent(item));
            if ((temporaryValue = response?.results) != null && temporaryValue.data) {
                results5.push(...response.results.data);
            }
        }
        catch {
        }
    const results6 = [...new Map(results5.map(item => [item.id, item])).values()];
    if (results6.length
        ===
            0) {
        throw new ScraperError("Anime not found");
    }
    const filteredItems = results6.filter(item => item.tvInfo.showType === "TV");
    const value7 = await myanimeFetchData(context, context.media, filteredItems, value);
    let results7 = [];
    if (value7 && value7.results.length > 0 && (results7 = value7.results.map(item => {
        const match = filteredItems.find(anime => anime.id === item.id);
        if (!match)
            return null;
        const result = { ...match };
        return result.seasonNum = item.season ?? 1, result;
    }).filter(item => item !== null).sort((left, right) => left.seasonNum - right.seasonNum)),
        results7.length
            ===
                0) {
        throw new ScraperError("Anime not found");
    }
    let url;
    let match = results7.find(item => item.seasonNum === context.media.season.number);
    const filteredItems2 = results7.filter(item => item.seasonNum === context.media.season.number);
    if (filteredItems2.length
        >
            1
        && (match = filteredItems2.sort((left3, right3) => {
            const title2 = left3.title, title3 = right3.title, title4 = context.media.season.title;
            return Number(fsharetvProcessData(title3, title4))
                -
                    Number(fsharetvProcessData(title2, title4));
        })[0]), match) {
        const response2 = await context.proxiedFetcher("https://myanime.aether.mom/api/episodes/" + match.id);
        if ((temporaryValue6 = response2?.results) != null && temporaryValue6.episodes) {
            const match2 = response2.results.episodes.find(item => item.episode_no === context.media.episode.number);
            if (match2) {
                (url = match2.id);
            }
        }
    }
    if (!url) {
        let number2 = context.media.episode.number;
        for (const temporaryValue8 of results7) {
            const value8 = temporaryValue8.tvInfo.sub ?? 0;
            if (number2 <= value8) {
                const value9 = number2;
                const response3 = await context.proxiedFetcher("https://myanime.aether.mom/api/episodes/" + temporaryValue8.id);
                if ((temporaryValue7 = response3?.results) != null && temporaryValue7.episodes) {
                    const match3 = response3.results.episodes.find(item => item.episode_no === value9);
                    if (match3) {
                        url = match3.id;
                        break;
                    }
                }
            }
            if (url) {
                break;
            }
            number2 -= value8;
        }
    }
    if (!url) {
        throw new ScraperError("Episode not found");
    }
    const embed = {
        embedId: "myanimesub",
        url: url
    };
    const embed3 = {
        embedId: "myanimedub",
        url: url
    };
    return {
        embeds: [embed, embed3]
    };
}
async function scrapeMyanimeMovie(context) {
    const response = await context.proxiedFetcher("https://myanime.aether.mom/api/search?keyword=" + encodeURIComponent(context.media.title));
    const item = response.results.data.find(item => item.tvInfo.showType === "Movie");
    if (!item) {
        throw new ScraperError("No watchable sources found");
    }
    const response2 = await context.proxiedFetcher("https://myanime.aether.mom/api/episodes/" + item.id);
    const match = response2.results.episodes.find(item => item.episode_no === 1);
    if (!match) {
        throw new ScraperError("No watchable sources found");
    }
    const embed = {
        embedId: "myanimesub",
        url: match.id
    };
    const embed3 = {
        embedId: "myanimedub",
        url: match.id
    };
    return {
        embeds: [embed, embed3]
    };
}
const myanimeProviderConfig = {
    id: "myanime",
    name: "MyAnime \uD83C\uDF38",
    rank: 810,
    disabled: true,
    flags: ["cors-allowed"],
    scrapeMovie: scrapeMyanimeMovie,
    scrapeShow: scrapeMyanimeShow
};
const myanimeProvider = createSourceProvider(myanimeProviderConfig);
const nhdapiValue = ["flixhq", "hollymoviehd"];
const nhdapiValue2 = "Mozilla/5.0 (Linux; Android 10; K) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Mobile Safari/537.36";
async function scrapeNhdapi(context) {
    const value = context.media.type === "movie" ? "movie/" + context.media.tmdbId : "tv/" + context.media.tmdbId + "/" + context.media.season.number + "/" + context.media.episode.number;
    const requestUrl = "https://server.nhdapi.xyz/" + nhdapiValue[0] + "/" + value;
    const requestOptions = {
        Accept: "*/*",
        Referer: "https://nhdapi.xyz/",
        "User-Agent": nhdapiValue2
    };
    const value4 = requestOptions;
    const requestOptions2 = {
        headers: value4
    };
    const response = await context.proxiedFetcher(requestUrl, requestOptions2);
    if (!(response != null && response.url)) {
        throw new ScraperError("No video URL found in API response");
    }
    context.progress(50);
    const url = response.url;
    const value5 = response.headers || {};
    const stream = {
        id: "primary",
        type: "hls",
        playlist: url,
        headers: value5,
        flags: [],
        captions: []
    };
    return {
        embeds: [],
        stream: [stream]
    };
}
const nhdapiProviderConfig = {
    id: "nhdapi",
    name: "NoHD \uD83C\uDF40",
    rank: 857,
    disabled: true,
    flags: ["cors-allowed"],
    scrapeMovie: scrapeNhdapi,
    scrapeShow: scrapeNhdapi
};
const nhdapiProvider = createSourceProvider(nhdapiProviderConfig);
const nunflixBaseUrl = "https://mama.up.railway.app/api/showbox";
async function scrapeNunflix(context) {
    const value = context.media.type === "movie" ? nunflixBaseUrl + "/movie/" + context.media.tmdbId : nunflixBaseUrl + "/tv/" + context.media.tmdbId + "?season=" + context.media.season.number + "&episode=" + context.media.episode.number;
    const response = await context.proxiedFetcher(value);
    if (!response) {
        throw new ScraperError("No response from API");
    }
    const value7 = await response;
    if (!value7.success) {
        throw new ScraperError("No streams found");
    }
    const value8 = Array.isArray(value7.streams) ? value7.streams : [value7.streams];
    if (value8.length
        ===
            0
        || !value8[0].player_streams) {
        throw new ScraperError("No valid streams found");
    }
    let value9 = value8[0];
    for (const item of value8)
        if (item.quality.includes("4K") || item.quality.includes("2160p")) {
            value9 = item;
            break;
        }
    const numericValue = value9.player_streams.reduce((accumulator, item) => {
        let value;
        if (item.quality
            ===
                "4K"
            || item.quality.includes("4K")) {
            value = 2160;
        }
        else {
            if (item.quality
                ===
                    "ORG"
                || item.quality.includes("ORG")) {
                return accumulator;
            }
            value =
                parseInt(item.quality.replace("P", ""), 10);
        }
        Number.isNaN(value) || accumulator[value] || (accumulator[value] = item.file);
        return accumulator;
    }, {});
    const stream = { ...numericValue[2160] && { "4k": { type: "mp4", url: numericValue[2160] } }, ...numericValue[1080] && { 1080: { type: "mp4", url: numericValue[1080] } }, ...numericValue[720] && { 720: { type: "mp4", url: numericValue[720] } }, ...numericValue[480] && { 480: { type: "mp4", url: numericValue[480] } }, ...numericValue[360] && { 360: { type: "mp4", url: numericValue[360] } } };
    const stream4 = {
        id: "primary",
        captions: [],
        qualities: stream,
        type: "file",
        flags: ["cors-allowed"]
    };
    return {
        embeds: [],
        stream: [stream4]
    };
}
const nunflixProviderConfig = {
    id: "nunflix",
    name: "NFLX-4K \uD83E\uDEBF",
    rank: 4,
    disabled: true,
    flags: ["cors-allowed"],
    scrapeMovie: scrapeNunflix,
    scrapeShow: scrapeNunflix
};
const nunflixProvider = createSourceProvider(nunflixProviderConfig);
const oneroomValue = atob("c3VwZXJzZWNyZXRrZXk=");
const oneroomBaseUrl = "https://reyna.bludclart.com/api/source/oneroom";
function oneroomCreateToken(input, argument2 = "", argument3 = "") {
    const value = input + ":" + argument2 + ":" + argument3;
    return CryptoJS.HmacSHA256(value, oneroomValue).toString(CryptoJS.enc.Hex);
}
async function scrapeOneroom(context) {
    let value = oneroomBaseUrl + "/" + context.media.tmdbId;
    let value8 = "";
    let value9 = "";
    if (context.media.type === "show") {
        (value8 = context.media.season.number.toString(), value9 = context.media.episode.number.toString(), value += "/" + value8 + "/" + value9);
    }
    const value10 = oneroomCreateToken(context.media.tmdbId, value8, value9);
    value += "?vrf=" + value10;
    const response = await context.proxiedFetcher(value);
    const url = response?.sources;
    if (!url || url.length === 0) {
        throw new ScraperError("Sources not found.");
    }
    context.progress(50);
    const result = {};
    for (const item of url) {
        const value11 = /([0-9]{3,4})p/.exec(item.label);
        const value12 = value11 ? value11[1] : "unknown";
        const stream = {
            type: "mp4",
            url: item.file
        };
        result[value12] = stream;
    }
    context.progress(90);
    const stream3 = {
        id: "primary",
        type: "file",
        qualities: result,
        flags: ["cors-allowed"],
        captions: []
    };
    return {
        embeds: [],
        stream: [stream3]
    };
}
const oneroomProviderConfig = {
    id: "oneroom",
    name: "OneRoom \uD83E\uDDAD",
    rank: 178,
    disabled: true,
    flags: ["cors-allowed"],
    scrapeMovie: scrapeOneroom,
    scrapeShow: scrapeOneroom
};
const oneroomProvider = createSourceProvider(oneroomProviderConfig);
const protonmoviesBaseUrl = "https://m3.protonmovies.top";
function protonmoviesExtractValue(text) {
    var temporaryValue;
    const match = text.match(/eval\(function\(p,a,c,k,e,d\)\{[\s\S]*?}\('(.*?)',(\d+),(\d+),'(.*?)'\.split\('\|'\)/);
    if (!match) {
        throw new ScraperError("Packed code not found");
    }
    const [, itemValue, , , itemValue2] = match;
    const value = itemValue2.split("|");
    const numericValue = itemValue.replace(/\b(\d+)\b/g, (argument1, argument2) => {
        const numericValue2 = parseInt(argument2, 10);
        if (numericValue2 <
            value.length
            && value[numericValue2]) {
            return value[numericValue2];
        }
        return argument1;
    });
    const result = {
        MDCore: {}
    };
    const value5 = result;
    if (new Function("MDCore", numericValue.replace(/^(\d+)\./gm, "MDCore."))(value5.MDCore), !((temporaryValue = value5.MDCore) != null && temporaryValue.wurl)) {
        throw new ScraperError("Could not resolve MDCore.wurl");
    }
    const url = String(value5.MDCore.wurl);
    return url.startsWith("//") ? "https:" + url : url;
}
function protonmoviesExtractValue2(text) {
    const match = text.match(/\["<div class[\s\S]*?\]\s*;/);
    return match ? match[0].slice(1, -2).split(/",\s*"/g).join("").replace(/^"|"$/g, "").replace(/\\"/g, '"').replace(/\\(?=\/)/g, "") : null;
}
async function scrapeProtonmovies(context) {
    const value = context.media.type === "show";
    const { title: title2 } = context.media;
    const result = {
        baseUrl: protonmoviesBaseUrl
    };
    const response = await context.proxiedFetcher("/search/" + encodeURIComponent(title2) + "/", result);
    const value18 = response.indexOf("</header>");
    if (value18 === -1) {
        throw new ScraperError("Search page structure not recognized");
    }
    const items = response.slice(value18 +
        9).split(`
`).map(item => item.trim()).filter(item => item.length > 0 && !item.startsWith("<!--"));
    if (items.length < 2) {
        throw new ScraperError("No results found");
    }
    const value19 = protonmoviesExtractValue2(items[1]);
    if (!value19) {
        throw new ScraperError("Failed to decode search results");
    }
    const url = /<a\s+href="([^"]+)"[^>]*aria-label="Download\s+([^"]+)"/g;
    const value20 = [...value19.matchAll(url)][0];
    if (!value20) {
        throw new ScraperError("No downloadable entries found");
    }
    const url3 = value20[1];
    const response2 = await context.proxiedFetcher("" + protonmoviesBaseUrl + url3);
    const items3 = response2.split(`
`).map(item => item.trim());
    const value21 = items3.findIndex(item => item.includes("</header>      <!--Nav End-->"));
    if (value21 === -1 || items3.length <=
        value21 +
            2) {
        throw new ScraperError("Detail page structure not recognized");
    }
    const value22 = protonmoviesExtractValue2(items3[value21 +
        2]);
    if (!value22) {
        throw new ScraperError("Failed to decode detail content");
    }
    let url4 = "";
    if (value) {
        const value23 = context;
        const url5 = value23.media.season.number.toString().padStart(2, "0");
        const url6 = value23.media.episode.number.toString().padStart(2, "0");
        const url7 = new RegExp("<a\\s+href=\"([^\"]*s" + url5 + "e" + url6 + "[^\"]*\\.html)\"");
        const match = value22.match(url7);
        if (match) {
            (url4 = match[1]);
        }
    }
    let url8 = "";
    if (url4) {
        const response3 = await context.proxiedFetcher("" + protonmoviesBaseUrl + url4);
        const match7 = response3.match(/var\s+url\s*=\s*"([^"]+)";/);
        if (match7) {
            (url8 = match7[1]);
        }
    }
    if (!url8) {
        const match8 = response2.match(/var\s+url\s*=\s*"([^"]+)";/);
        if (match8) {
            (url8 = match8[1]);
        }
    }
    let value24 = "";
    if (url8) {
        const response4 = await context.proxiedFetcher("" + protonmoviesBaseUrl + url8);
        const value25 = response4 ? Object.values(response4)[0] : void 0;
        if (value25) {
            for (const item of Object.values(value25))
                if (item &&
                    typeof item
                        ===
                            "object" && item.link) {
                    value24 = item.link;
                    break;
                }
        }
    }
    if (!value24) {
        throw new ScraperError("Failed to extract episode link");
    }
    const response5 = await context.proxiedFetcher(value24);
    const value26 = /<script>[\s\S]*?MDCore\.ref\s*=\s*"[^"]*"[\s\S]*?eval\(function\(p,a,c,k,e,d\)[\s\S]*?<\/script>/;
    const match9 = response5.match(value26);
    if (!match9) {
        throw new ScraperError("Obfuscated script not found");
    }
    const extractedKey = protonmoviesExtractValue(match9[0]);
    if (!extractedKey) {
        throw new ScraperError("Failed to resolve final mp4");
    }
    context.progress(90);
    const requestOptions = {
        id: "primary",
        type: "file",
        qualities: {},
        headers: {},
        flags: [],
        captions: []
    };
    requestOptions.qualities.unknown = {};
    requestOptions.qualities.unknown.type = "mp4";
    requestOptions.qualities.unknown.url = extractedKey;
    requestOptions.headers.origin = "https://mixdrop.cv";
    requestOptions.headers.Referer = "https://mixdrop.cv/";
    return {
        embeds: [],
        stream: [requestOptions]
    };
}
const protonmoviesProviderConfig = {
    id: "protonmovies",
    name: "ProtonMovies \u269B",
    rank: 201,
    flags: [],
    scrapeMovie: scrapeProtonmovies,
    scrapeShow: scrapeProtonmovies
};
const protonmoviesProvider = createSourceProvider(protonmoviesProviderConfig);
const rgshowsValue = "api.rgshows.ru";
const rgshowsValue2 = {
    referer: "https://rgshows.ru/",
    origin: "https://rgshows.ru",
    host: rgshowsValue,
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
};
const rgshowsValue3 = rgshowsValue2;
async function scrapeRgshows(context) {
    var temporaryValue;
    let requestUrl = "https://" + rgshowsValue + "/main";
    context.media.type === "movie" ? requestUrl += "/movie/" + context.media.tmdbId : context.media.type === "show" && (requestUrl += "/tv/" + context.media.tmdbId + "/" + context.media.season.number + "/" + context.media.episode.number);
    const requestOptions = {
        headers: rgshowsValue3
    };
    const response = await context.proxiedFetcher(requestUrl, requestOptions);
    if (!((temporaryValue = response?.stream) != null && temporaryValue.url)) {
        throw new ScraperError("No streams found");
    }
    if (response.stream.url === "https://vidzee.wtf/playlist/69/master.m3u8") {
        throw new ScraperError("Found only vidzee porn stream");
    }
    context.progress(100);
    return { embeds: [], stream: [{ id: "primary", type: "hls", playlist: buildProxiedHlsUrl(response.stream.url, context.features, rgshowsValue3), flags: ["cors-allowed"], captions: [], headers: rgshowsValue3 }] };
}
const rgshowsProviderConfig = {
    id: "rgshows",
    name: "RGShows \uD83D\uDC1B",
    rank: 173,
    disabled: true,
    flags: ["cors-allowed"],
    scrapeMovie: scrapeRgshows,
    scrapeShow: scrapeRgshows
};
async function scrapeRidomovies(context) {
    const response = await context.proxiedFetcher("/search", { baseUrl: ridomoviesValue, query: { q: context.media.title } });
    const items4 = response.data.items.map(item => {
        const title2 = item.title;
        const value = item.contentable.releaseYear;
        const value7 = item.fullSlug;
        return {
            name: title2,
            year: value,
            fullSlug: value7
        };
    });
    const item = items4.find(item => item.name === context.media.title && item.year === context.media.releaseYear.toString());
    if (!(item != null && item.fullSlug)) {
        throw new ScraperError("No watchable item found");
    }
    context.progress(40);
    let value = "/" + item.fullSlug + "/videos";
    if (context.media.type === "show") {
        const embed = {
            baseUrl: ridomoviesBaseUrl
        };
        const response2 = await context.proxiedFetcher("/" + item.fullSlug, embed);
        const value6 = "season-" + context.media.season.number + "/episode-" + context.media.episode.number;
        const value7 = new RegExp("\\\\\"id\\\\\":\\\\\"(\\d+)\\\\\"(?=.*?\\\\\\\"fullSlug\\\\\\\":\\\\\\\"[^\"]*" + value6 + "[^\"]*\\\\\\\")", "g");
        const results = [...response2.matchAll(value7)];
        const items5 = results.map(item => item[1]);
        if (items5.length
            ===
                0) {
            throw new ScraperError("No watchable item found");
        }
        const value8 = items5.at(-1);
        value = "/episodes/" + value8 + "/videos";
    }
    const result = {
        baseUrl: ridomoviesValue
    };
    const response3 = await context.proxiedFetcher(value, result);
    const document = loadHtml(response3.data[0].url);
    const url = document("iframe").attr("data-src");
    if (!url) {
        throw new ScraperError("No watchable item found");
    }
    context.progress(60);
    const results3 = [];
    if (url.includes("closeload")) {
        const embed4 = {
            embedId: closeloadEmbedProvider.id,
            url: url
        };
        results3.push(embed4);
    }
    if (url.includes("ridoo")) {
        const embed5 = {
            embedId: ridooEmbedProvider.id,
            url: url
        };
        results3.push(embed5);
    }
    context.progress(90);
    return {
        embeds: results3
    };
}
const rgshowsProvider = createSourceProvider(rgshowsProviderConfig);
const ridomoviesBaseUrl = "https://ridomovies.tv";
const ridomoviesValue = ridomoviesBaseUrl + "/core/api";
const ridomoviesProviderConfig = {
    id: "ridomovies",
    name: "RidoMovies \uD83E\uDD95",
    rank: 190,
    flags: [],
    disabled: true,
    scrapeMovie: scrapeRidomovies,
    scrapeShow: scrapeRidomovies
};
const ridomoviesProvider = createSourceProvider(ridomoviesProviderConfig);
const sezonlukdiziBaseUrl = "https://sezonlukdizi6.com";
async function scrapeSezonlukdiziShow(context) {
    context.progress(10);
    const response = await context.proxiedFetcher(sezonlukdiziBaseUrl + "/diziler.asp?adi=" + encodeURIComponent(context.media.title));
    const document = loadHtml(response);
    let temporaryValue;
    if (document("a.column").each((index, element) => {
        const value = document(element), value3 = value.attr("title");
        if (value3 && fsharetvProcessData(value3.replace(" izle", ""), context.media.title))
            return temporaryValue = value.attr("href"), false;
    }), !temporaryValue) {
        throw new ScraperError("Could not find a matching media item on search results");
    }
    context.progress(30);
    let url;
    if (context.media.type
        === "show") {
        const value = temporaryValue.replace("/diziler/", "").replace(".html", "");
        url = sezonlukdiziBaseUrl + "/" + value + "/dublaj/" + context.media.season.number + "-sezon-" + context.media.episode.number + "-bolum.html";
    }
    else {
        url = "" + sezonlukdiziBaseUrl + temporaryValue;
    }
    context.progress(60);
    const response2 = await context.proxiedFetcher(url);
    const document3 = loadHtml(response2);
    const dataId = document3("#dilsec[data-dil=\"0\"]").attr("data-id");
    if (!dataId) {
        throw new ScraperError("Could not find episode ID");
    }
    const requestOptions = {
        baseUrl: sezonlukdiziBaseUrl,
        method: "POST",
        body: "bid=" + dataId + "&dil=0",
        headers: {}
    };
    requestOptions.headers["Content-Type"] = "application/x-www-form-urlencoded; charset=UTF-8";
    requestOptions.headers["X-Requested-With"] = "XMLHttpRequest";
    requestOptions.headers.Referer = url;
    const response3 = await context.proxiedFetcher("/ajax/dataAlternatif22.asp", requestOptions);
    const data = JSON.parse(response3);
    if (data.status
        !== "success") {
        throw new ScraperError("Failed to fetch alternatives");
    }
    const document4 = data.data.map(async (item) => {
        try {
            ;
            {
                const requestOptions = {
                    "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
                    "X-Requested-With": "XMLHttpRequest",
                    Referer: url
                };
                const requestOptions3 = {
                    baseUrl: sezonlukdiziBaseUrl,
                    method: "POST",
                    body: "id=" + item.id,
                    headers: requestOptions
                };
                const response = await context.proxiedFetcher("/ajax/dataEmbed22.asp", requestOptions3);
                const document = loadHtml(response);
                let url = document("iframe").attr("src");
                if (url) {
                    return url.startsWith("//") && (url = "https:" + url), { embedId: item.baslik.toLowerCase(), url: url };
                }
            }
        }
        catch (error) {
            if (error instanceof ScraperError) {
                return null;
            }
            throw error;
        }
        return null;
    });
    const filteredItems = (await Promise.all(document4)).filter(item => item !== null);
    if (filteredItems.length === 0) {
        throw new ScraperError("Could not find any embeds");
    }
    context.progress(90);
    return {
        embeds: filteredItems
    };
}
const sezonlukdiziProviderConfig = {
    id: "sezonlukdizi",
    name: "SzDizi \uD83C\uDF6D(Turkish)",
    rank: 830,
    disabled: true,
    flags: ["cors-allowed"],
    scrapeShow: scrapeSezonlukdiziShow
};
const sezonlukdiziProvider = createSourceProvider(sezonlukdiziProviderConfig);
const slidemoviesBaseUrl = "https://pupp.slidemovies-dev.workers.dev";
async function scrapeSlidemovies(context) {
    const value = context.media.type === "movie" ? slidemoviesBaseUrl + "/movie/" + context.media.tmdbId : slidemoviesBaseUrl + "/tv/" + context.media.tmdbId + "/" + context.media.season.number + "/-" + context.media.episode.number;
    const response = await context.proxiedFetcher(value);
    const document = loadHtml(response);
    context.progress(50);
    const url = document("media-player").attr("src");
    if (!url) {
        throw new ScraperError("Stream URL not found");
    }
    const parsedUrl = new URL(url);
    const url3 = parsedUrl.searchParams.get("url") || "";
    const value5 = decodeURIComponent(url3);
    const language = document("media-provider track").map((item, index) => {
        {
            const url = document(index).attr("src") || "";
            const value8 = document(index).attr("lang") || "unknown";
            const language = normalizeLanguageCode(value8)
                || value8;
            const value9 = url.endsWith(".vtt") ? "vtt" : "srt";
            return {
                type: value9,
                id: url,
                url: url,
                language: language,
                hasCorsRestrictions: false
            };
        }
    }).get();
    context.progress(90);
    const stream = {
        id: "primary",
        type: "hls",
        flags: [],
        playlist: value5,
        captions: language
    };
    return {
        embeds: [],
        stream: [stream]
    };
}
const slidemoviesProviderConfig = {
    id: "slidemovies",
    name: "SlideMovies \uD83D\uDE1E",
    rank: 135,
    disabled: true,
    flags: ["cors-allowed"],
    scrapeMovie: scrapeSlidemovies,
    scrapeShow: scrapeSlidemovies
};
async function scrapeSoapertv(context) {
    const response = await context.proxiedFetcher("/search.html", { baseUrl: soapertvBaseUrl, query: { keyword: context.media.title } });
    const document = loadHtml(response);
    const captions = [];
    document(".thumbnail").each((index, element) => {
        const title2 = document(element).find("h5").find("a").first().text().trim();
        const match = document(element).find(".img-tip").first().text().trim();
        const url = document(element).find("h5").find("a").first().attr("href");
        !title2 || !url || captions.push({ title: title2, year: match ? parseInt(match, 10) : void 0, url: url });
    });
    let item = captions.find(item => item && fsharetvProcessData2(context.media, item.title, item.year))?.url;
    if (!item) {
        throw new ScraperError("Content not found");
    }
    if (context.media.type
        === "show") {
        const number2 = context.media.season.number;
        const number3 = context.media.episode.number;
        const stream = {
            baseUrl: soapertvBaseUrl
        };
        const response2 = await context.proxiedFetcher(item, stream);
        const document4 = loadHtml(response2);
        const value = document4("h4").filter((item, index3) => document4(index3).text().trim().split(":")[0].trim() === "Season" + number2).parent();
        const match = value.find("a").toArray();
        item = document4(match.find(item => parseInt(document4(item).text().split(".")[0], 10) === number3)).attr("href");
    }
    if (!item) {
        throw new ScraperError("Content not found");
    }
    const result = {
        baseUrl: soapertvBaseUrl
    };
    const response3 = await context.proxiedFetcher(item, result);
    const document5 = loadHtml(response3);
    const value9 = document5("#hId").attr("value");
    if (!value9) {
        throw new ScraperError("Content not found");
    }
    context.progress(50);
    const queryParams = new URLSearchParams;
    queryParams.append("pass", value9);
    queryParams.append("e2", "0");
    queryParams.append("server", "0");
    const value10 = context.media.type === "show" ? "/home/index/getEInfoAjax" : "/home/index/getMInfoAjax";
    const requestOptions = {
        baseUrl: soapertvBaseUrl,
        method: "POST",
        body: queryParams,
        headers: {}
    };
    requestOptions.headers.referer = "" + soapertvBaseUrl + item;
    requestOptions.headers["User-Agent"] = "Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.0 Mobile/15E148 Safari/604.1";
    requestOptions.headers["Viewport-Width"] = "375";
    const response4 = await context.proxiedFetcher(value10, requestOptions);
    const data = JSON.parse(response4);
    const captions3 = [];
    if (Array.isArray(data.subs)) {
        for (const temporaryValue3 of data.subs) {
            let value11 = "";
            if (temporaryValue3.name.includes(".srt")) {
                const parts = temporaryValue3.name.split(".srt")[0].trim();
                value11 =
                    normalizeLanguageCode(parts);
            }
            else if (temporaryValue3.name.includes(":")) {
                const parts2 = temporaryValue3.name.split(":")[0].trim();
                value11 = normalizeLanguageCode(parts2);
            }
            else {
                const value12 = temporaryValue3.name.trim();
                value11 = normalizeLanguageCode(value12);
            }
            if (!value11) {
                continue;
            }
            const caption = {
                id: temporaryValue3.path,
                url: "" + soapertvBaseUrl + temporaryValue3.path,
                type: "srt",
                hasCorsRestrictions: false,
                language: value11
            };
            captions3.push(caption);
        }
    }
    context.progress(90);
    const requestOptions2 = {
        referer: "" + soapertvBaseUrl + item,
        "User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.0 Mobile/15E148 Safari/604.1",
        "Viewport-Width": "375",
        Origin: soapertvBaseUrl
    };
    const url = requestOptions2;
    return { embeds: [], stream: [{ id: "primary", playlist: await hollymoviehdDecodePayload(context.proxiedFetcher, soapertvBaseUrl + "/" + data.val, url), type: "hls", proxyDepth: 2, flags: ["cors-allowed"], captions: captions3 }, ...data.val_bak ? [{ id: "backup", playlist: await hollymoviehdDecodePayload(context.proxiedFetcher, soapertvBaseUrl + "/" + data.val_bak, url), type: "hls", flags: ["cors-allowed"], proxyDepth: 2, captions: captions3 }] : []] };
}
const slidemoviesProvider = createSourceProvider(slidemoviesProviderConfig);
const soapertvBaseUrl = "https://soaper.cc";
const soapertvProviderConfig = {
    id: "soapertv",
    name: "SoaperTV",
    rank: 130,
    disabled: true,
    flags: ["cors-allowed"],
    scrapeMovie: scrapeSoapertv,
    scrapeShow: scrapeSoapertv
};
const soapertvProvider = createSourceProvider(soapertvProviderConfig);
const solsticeBaseUrl = "https://mbp.aether.mom";
function solsticeMapQuality(input) {
    const value = input.list.reduce((accumulator, item) => {
        const { path: path2, quality: quality2, format: format2 } = item;
        const value = item.real_quality;
        if (format2 !== "mp4") {
            return accumulator;
        }
        let value4;
        if (quality2 ===
            "4K"
            ||
                value ===
                    "4K") {
            value4 = 2160;
        }
        else if (quality2.toLowerCase()
            ===
                "org"
            ||
                value.toLowerCase()
                    === "org") {
            value4 = "unknown";
        }
        else {
            ;
            {
                const normalizedValue = quality2.replace("p", "");
                value4 = parseInt(normalizedValue, 10);
            }
        }
        typeof value4
            === "number"
            && Number.isNaN(value4) || accumulator[value4] || (accumulator[value4] = path2);
        return accumulator;
    }, {});
    const value3 = Object.entries(value).reduce((accumulator3, [i, W]) => (accumulator3[i] = W, accumulator3), {});
    return { ...value3[2160] && { "4k": { type: "mp4", url: value3[2160] } }, ...value3[1080] && { 1080: { type: "mp4", url: value3[1080] } }, ...value3[720] && { 720: { type: "mp4", url: value3[720] } }, ...value3[480] && { 480: { type: "mp4", url: value3[480] } }, ...value3[360] && { 360: { type: "mp4", url: value3[360] } }, ...value3.unknown && { unknown: { type: "mp4", url: value3.unknown } } };
}
async function solsticeFetchData(context, argument2, argument3, argument4, argument5) {
    const value = solsticeBaseUrl + "/search?q=" + encodeURIComponent(argument3) + "&type=" + argument4 + (argument5 ? "&year=" + argument5 : "");
    const response = await context.proxiedFetcher(value);
    if (!response.data || response.data.length === 0) {
        throw new ScraperError("No results found in search");
    }
    for (const item of response.data) {
        const url = solsticeBaseUrl + "/details/" + argument4 + "/" + item.id;
        const response2 = await context.proxiedFetcher(url);
        if (response2.data &&
            response2.data.tmdb_id.toString()
                === argument2) {
            return item.id;
        }
    }
    throw new ScraperError("Could not find matching media item for TMDB ID");
}
async function scrapeSolsticeMovie(context) {
    var temporaryValue;
    const tmdbId2 = context.media.tmdbId;
    const title2 = context.media.title;
    const value = (temporaryValue = context.media.releaseYear) == null ? void 0 : temporaryValue.toString();
    if (!tmdbId2 || !title2) {
        throw new ScraperError("Missing required media information");
    }
    const url = await solsticeFetchData(context, tmdbId2, title2, "movie", value);
    const requestUrl = solsticeBaseUrl + "/movie/" + url;
    const response = await context.proxiedFetcher(requestUrl);
    if (!response.data || !response.data.list) {
        ;
        throw new ScraperError("No streams found for this movie");
    }
    const value4 = solsticeMapQuality(response.data);
    const stream = {
        id: "solstice",
        type: "file",
        qualities: value4,
        flags: ["cors-allowed"],
        captions: []
    };
    return {
        stream: [stream],
        embeds: []
    };
}
async function scrapeSolsticeShow(context) {
    var temporaryValue;
    const tmdbId2 = context.media.tmdbId;
    const title2 = context.media.title;
    const value = (temporaryValue = context.media.releaseYear) == null ? void 0 : temporaryValue.toString();
    const number2 = context.media.season.number;
    const number3 = context.media.episode.number;
    if (!tmdbId2 || !title2 || !number2 || !number3) {
        throw new ScraperError("Missing required media information");
    }
    const url = await solsticeFetchData(context, tmdbId2, title2, "tv", value);
    const requestUrl = solsticeBaseUrl + "/tv/" + url + "/" + number2 + "/" + number3;
    const response = await context.proxiedFetcher(requestUrl);
    if (!response.data || !response.data.list) {
        throw new ScraperError("No streams found for this episode");
    }
    const value4 = solsticeMapQuality(response.data);
    const stream = {
        id: "primary",
        type: "file",
        qualities: value4,
        flags: ["cors-allowed"],
        captions: []
    };
    return {
        embeds: [],
        stream: [stream]
    };
}
const solsticeProviderConfig = {
    id: "solstice",
    name: "Solstice (4K) \u2744\uFE0F",
    rank: 785,
    disabled: true,
    flags: ["cors-allowed"],
    scrapeMovie: scrapeSolsticeMovie,
    scrapeShow: scrapeSolsticeShow
};
const solsticeProvider = createSourceProvider(solsticeProviderConfig);
const streamboxBaseUrl = "https://vidjoy.pro/embed/api/fastfetch";
async function scrapeStreambox(context) {
    const response = await context.proxiedFetcher(context.media.type === "movie" ? streamboxBaseUrl + "/" + context.media.tmdbId + "?sr=0" : streamboxBaseUrl + "/" + context.media.tmdbId + "/" + context.media.season.number + "/" + context.media.episode.number + "?sr=0");
    if (!response) {
        throw new ScraperError("Failed to fetch StreamBox data");
    }
    console.log(response);
    const value = await response;
    const result = {};
    value.url.forEach(item => {
        result[item.resulation] = item.link;
    });
    const items = value.tracks.map(item => ({ id: item.lang, url: item.url, language: item.code, type: "srt" }));
    if (value.provider === "MovieBox") {
        const requestOptions = {
            Referer: value.headers?.Referer
        };
        const requestOptions2 = {
            id: "primary",
            captions: items,
            qualities: { ...result["1080"] && { 1080: { type: "mp4", url: result["1080"] } }, ...result["720"] && { 720: { type: "mp4", url: result["720"] } }, ...result["480"] && { 480: { type: "mp4", url: result["480"] } }, ...result["360"] && { 360: { type: "mp4", url: result["360"] } } },
            type: "file",
            flags: ["cors-allowed"],
            preferredHeaders: requestOptions
        };
        return {
            embeds: [],
            stream: [requestOptions2]
        };
    }
    const item = value.url.find(item => item.type === "hls") || value.url[0];
    const requestOptions3 = {
        Referer: value.headers?.Referer
    };
    const stream = {
        id: "primary",
        captions: items,
        playlist: item.link,
        type: "hls",
        flags: ["cors-allowed"],
        preferredHeaders: requestOptions3
    };
    return {
        embeds: [],
        stream: [stream]
    };
}
const streamboxProviderConfig = {
    id: "streambox",
    name: "MovieBox \uD83D\uDC13",
    rank: 89,
    disabled: true,
    flags: ["cors-allowed"],
    scrapeMovie: scrapeStreambox,
    scrapeShow: scrapeStreambox
};
const streamboxProvider = createSourceProvider(streamboxProviderConfig);
const timeBaseUrl = "https://8ball.piracy.cloud/api/generate-secure-url";
async function scrapeTimeMovie(context) {
    const response = await context.proxiedFetcher(timeBaseUrl, { method: "POST", body: { filePath: "/media/" + context.media.tmdbId + "/master.m3u8" } });
    const value = response?.secureUrl;
    if (!value) {
        throw new ScraperError("No secure URL generated");
    }
    return { embeds: [], stream: [{ id: "primary", type: "hls", playlist: buildProxiedHlsUrl(value, context.features, { Referer: "https://8ball.piracy.cloud/", Origin: "https://8ball.piracy.cloud" }), flags: ["cors-allowed"], captions: [] }] };
}
async function scrapeTimeShow(context) {
    const response = await context.proxiedFetcher(timeBaseUrl, { method: "POST", body: { filePath: "/media/" + context.media.tmdbId + "-" + context.media.season.number + "-" + context.media.episode.number + "/master.m3u8" } });
    const value = response?.secureUrl;
    if (!value) {
        throw new ScraperError("No secure URL generated");
    }
    return { embeds: [], stream: [{ id: "primary", type: "hls", playlist: buildProxiedHlsUrl(value, context.features, { Referer: "https://8ball.piracy.cloud/", Origin: "https://8ball.piracy.cloud" }), flags: ["cors-allowed"], captions: [] }] };
}
const timeProviderConfig = {
    id: "time",
    name: "Time \u23F3",
    rank: 878,
    disabled: true,
    flags: ["cors-allowed"],
    scrapeMovie: scrapeTimeMovie,
    scrapeShow: scrapeTimeShow
};
const timeProvider = createSourceProvider(timeProviderConfig);
const trinityValue = ["Zen", "Noah", "Ophim", "Hollywood", "Atom", "Lightning", "Smash", "Mega", "Zoom", "Rizz", "alpha", "bravo", "charlie", "delta", "echo", "golf", "Comet", "Pulsar", "MadPlay"];
async function scrapeTrinity(context) {
    const results = [];
    const stream = {
        type: context.media.type,
        tmdbId: context.media.tmdbId
    };
    const value = stream;
    if (context.media.type === "show") {
        value.season = context.media.season.number, value.episode = context.media.episode.number;
    }
    for (const item of trinityValue) {
        const result = { ...value };
        results.push({ embedId: "cinemaos-" + item, url: JSON.stringify(result) });
    }
    context.progress(50);
    return {
        embeds: results
    };
}
const trinityProviderConfig = {
    id: "trinity",
    name: "Trinity \uD83D\uDD25",
    rank: 178,
    disabled: true,
    flags: ["cors-allowed"],
    scrapeMovie: scrapeTrinity,
    scrapeShow: scrapeTrinity
};
const trinityProvider = createSourceProvider(trinityProviderConfig);
const twinkBaseUrl = "https://lvscfjzvqjootupktgcrwwht.lordflix.club";
const twinkValue = "/gDw1A9XOfc6ej-SC1jS_sw/ty/2024-08-31/issoz/NVSLay.srt#en";
function twinkDecodePayload(input) {
    const token = CryptoJS.enc.Base64.parse(input);
    const token6 = CryptoJS.lib.WordArray.create(token.words.slice(0, 4));
    const token7 = CryptoJS.lib.WordArray.create(token.words.slice(4), token.sigBytes - 16);
    const signature = CryptoJS.SHA256(twinkValue);
    const result = {
        ciphertext: token7
    };
    const token8 = CryptoJS.AES.decrypt(result, signature, { iv: token6, mode: CryptoJS.mode.CBC, padding: CryptoJS.pad.Pkcs7 });
    const token9 = token8.toString(CryptoJS.enc.Utf8);
    const value = token9.split("").reverse().join("");
    if (!value) {
        throw new Error("Failed to decrypt or empty result");
    }
    return JSON.parse(value);
}
async function scrapeTwink(context) {
    let temporaryValue;
    context.media.type === "movie" ? temporaryValue = "/lala/" + context.media.tmdbId : temporaryValue = "/lala/" + context.media.tmdbId + "/" + context.media.season.number + "/" + context.media.episode.number;
    const result = {
        baseUrl: twinkBaseUrl
    };
    const response = await context.fetcher(temporaryValue, result);
    const value = twinkDecodePayload(response);
    if (!value.source) {
        throw new ScraperError("No source found");
    }
    const captions = [];
    if (value.subtitle) {
        for (const [itemValue, itemValue2] of Object.entries(value.subtitle)) {
            let language = normalizeLanguageCode(itemValue);
            !language && isValidLanguageCode(itemValue) && (language = itemValue);
            language && captions.push({ id: language, language: language, url: itemValue2.startsWith("http") ? itemValue2 : new URL(itemValue2, twinkBaseUrl).toString(), type: itemValue2.includes(".vtt") ? "vtt" : "srt", hasCorsRestrictions: false });
        }
    }
    const stream = {
        id: "primary",
        type: "hls",
        playlist: value.source,
        flags: ["cors-allowed"],
        captions: captions
    };
    return {
        embeds: [],
        stream: [stream]
    };
}
const twinkProviderConfig = {
    id: "twink",
    name: "Lerlix",
    rank: 885,
    disabled: true,
    flags: ["cors-allowed"],
    scrapeMovie: scrapeTwink,
    scrapeShow: scrapeTwink
};
const twinkProvider = createSourceProvider(twinkProviderConfig);
const uiraliveBaseUrl = "https://xj4h5qk3tf7v2mlr9s.uira.live/";
async function scrapeUiralive(context) {
    const value = uiraliveBaseUrl + "all/" + context.media.tmdbId + (context.media.type === "movie" ? "" : "?s=" + context.media.season.number + "&e=" + context.media.episode.number);
    let temporaryValue;
    try {
        temporaryValue = await context.fetcher(value);
    }
    catch (temporaryValue4) {
        throw temporaryValue4 instanceof ScraperError
            ? new ScraperError("" + temporaryValue4.message) : temporaryValue4;
    }
    if (!temporaryValue) {
        try {
            temporaryValue = await context.fetcher(value);
        }
        catch (temporaryValue5) {
            throw temporaryValue5 instanceof ScraperError ? new ScraperError("" + temporaryValue5.message) : temporaryValue5;
        }
    }
    if (!temporaryValue || !temporaryValue.sources ||
        temporaryValue.sources.length
            ===
                0) {
        throw new ScraperError("No sources found");
    }
    if (context.progress(90), !temporaryValue.sources[0].url) {
        throw new Error("Source URL is missing");
    }
    const stream = {
        id: "primary",
        playlist: temporaryValue.sources[0].url,
        type: "hls",
        flags: ["cors-allowed"],
        captions: temporaryValue.captions || []
    };
    return {
        embeds: [],
        stream: [stream]
    };
}
const uiraliveProviderConfig = {
    id: "uiralive",
    name: "Uira \uD83D\uDD25",
    rank: 235,
    disabled: true,
    flags: ["cors-allowed"],
    scrapeMovie: scrapeUiralive,
    scrapeShow: scrapeUiralive
};
const uiraliveProvider = createSourceProvider(uiraliveProviderConfig);
const vidapiClickBaseUrl = "https://vidapi.click";
async function scrapeVidapiClick(context) {
    const value = context.media.type === "show" ? vidapiClickBaseUrl + "/api/video/tv/" + context.media.tmdbId + "/" + context.media.season.number + "/" + context.media.episode.number : vidapiClickBaseUrl + "/api/video/movie/" + context.media.tmdbId;
    const result = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    };
    const requestOptions = {
        headers: result
    };
    const response = await context.proxiedFetcher(value, requestOptions);
    if (!response) {
        throw new ScraperError("Failed to fetch video source");
    }
    if (!response.sources[0].file) {
        throw new ScraperError("No video source found");
    }
    context.progress(50);
    context.progress(90);
    const stream = {
        id: "primary",
        type: "hls",
        playlist: response.sources[0].file,
        flags: ["cors-allowed"],
        captions: []
    };
    return {
        embeds: [],
        stream: [stream]
    };
}
const vidapiClickProviderConfig = {
    id: "vidapi-click",
    name: "VidApi \uD83D\uDC19",
    rank: 499,
    disabled: true,
    flags: ["cors-allowed"],
    scrapeMovie: scrapeVidapiClick,
    scrapeShow: scrapeVidapiClick
};
const vidapiClickProvider = createSourceProvider(vidapiClickProviderConfig);
const vidfastBaseUrl = "https://fast.aether.cx";
function vidfastProcessData(input) {
    return "vidfast-" + input.toLowerCase().replace(/[^a-z0-9]+/gu, "");
}
function vidfastBuildRequestUrl(context) {
    const queryParams = new URLSearchParams({ type: context.media.type === "movie" ? "movie" : "show", tmdbId: String(context.media.tmdbId) });
    context.media.type === "show" && (queryParams.set("season", String(context.media.season.number)), queryParams.set("episode", String(context.media.episode.number)));
    return vidfastBaseUrl + "/scrape?" + queryParams.toString();
}
async function vidfastResolveStream(context) {
    context.progress(30);
    const response = await context.fetcher(vidfastBuildRequestUrl(context));
    if (!response.streams || response.streams.length === 0) {
        throw new ScraperError("No VidFast streams found");
    }
    context.progress(80);
    const items = response.streams.filter(item => typeof item.url == "string" && item.url.length > 0).map(item => ({ embedId: vidfastProcessData(item.name), url: JSON.stringify({ url: item.url, noReferrer: item.noReferrer ?? false, headers: item.headers ?? void 0, captions: item.captions ?? [], name: item.name, description: item.description }) }));
    if (items.length
        ===
            0) {
        throw new ScraperError("No VidFast streams found");
    }
    context.progress(100);
    return items;
}
async function scrapeVidfastMovie(context) {
    return ({ embeds: await vidfastResolveStream(context) });
}
async function scrapeVidfastShow(context) {
    return ({ embeds: await vidfastResolveStream(context) });
}
const vidfastSourceProvider = createSourceProvider({ id: "vidfast", name: "Fast (4K) \u26A1", rank: 1e3, disabled: true, flags: ["cors-allowed"], scrapeMovie: scrapeVidfastMovie, scrapeShow: scrapeVidfastShow });
async function scrapeVidify(context) {
    const value = { type: context.media.type, title: context.media.title, tmdbId: context.media.tmdbId, imdbId: context.media.imdbId, ...context.media.type === "show" && { season: context.media.season.number, episode: context.media.episode.number } };
    value.releaseYear = context.media.releaseYear;
    const value3 = value;
    return { embeds: [{ embedId: "vidify-alfa", url: JSON.stringify(value3) }, { embedId: "vidify-bravo", url: JSON.stringify(value3) }, { embedId: "vidify-charlie", url: JSON.stringify(value3) }, { embedId: "vidify-delta", url: JSON.stringify(value3) }, { embedId: "vidify-echo", url: JSON.stringify(value3) }, { embedId: "vidify-foxtrot", url: JSON.stringify(value3) }, { embedId: "vidify-golf", url: JSON.stringify(value3) }, { embedId: "vidify-hotel", url: JSON.stringify(value3) }, { embedId: "vidify-india", url: JSON.stringify(value3) }, { embedId: "vidify-juliett", url: JSON.stringify(value3) }] };
}
const vidifyProviderConfig = {
    id: "vidify",
    name: "Vidify \u2728",
    rank: 155,
    disabled: true,
    flags: ["cors-allowed"],
    scrapeMovie: scrapeVidify,
    scrapeShow: scrapeVidify
};
const vidifyProvider = createSourceProvider(vidifyProviderConfig);
const vidlinkBaseUrl = "https://vidlink.pro";
const vidlinkServerUrls = ["https://r1.aether.cx", "https://r2.aether.cx", "https://r3.aether.cx", "https://r4.aether.cx", "https://r5.aether.cx"];
const vidlinkValue = {
    Referer: "https://vidlink.pro/",
    Origin: "https://vidlink.pro"
};
const vidlinkValue2 = vidlinkValue;
const vidlinkValue3 = "c75136c5668bbfe65a7ecad431a745db68b5f381555b38d8f6c699449cf11fcd";
function vidlinkSelectServer() {
    return vidlinkServerUrls[Math.floor(Math.random() * vidlinkServerUrls.length)];
}
function vidlinkBuildRequestUrl(input) {
    const parsedUrl = new URL("/m3u8-proxy", vidlinkSelectServer());
    parsedUrl.searchParams.set("url", input);
    parsedUrl.searchParams.set("headers", JSON.stringify(vidlinkValue2));
    return parsedUrl.toString();
}
function vidlinkProcessData(input) {
    const value = new Uint8Array(input.length / 2);
    for (let value3 = 0; value3 < input.length; value3 += 2)
        value[value3 /
            2] =
            parseInt(input.substr(value3, 2), 16);
    return value;
}
function vidlinkDecodePayload(input) {
    let value = "";
    const byteLength2 = input.byteLength;
    for (let value3 = 0; value3 < byteLength2; value3++)
        value += String.fromCharCode(input[value3]);
    return btoa(value).replace(/\+/g, "-").replace(/\//g, "_").replace(/=/g, "");
}
function vidlinkProcessData2(input) {
    const value = vidlinkProcessData(vidlinkValue3);
    const timestamp = Math.floor(Date.now() / 1e3) + 43200;
    const value8 = new TextEncoder().encode(input);
    const value9 = new Uint8Array(8);
    new DataView(value9.buffer).setBigUint64(0, BigInt(timestamp), false);
    const value10 = new Uint8Array(value8.length + value9.length);
    value10.set(value8);
    value10.set(value9, value8.length);
    const value11 = new Uint8Array(24);
    const value12 = uA.secretbox(value10, value11, value);
    const value13 = new Uint8Array(value11.length + value12.length);
    value13.set(value11, 0);
    value13.set(value12, value11.length);
    return vidlinkDecodePayload(value13);
}
async function scrapeVidlinkMovie(context) {
    var temporaryValue;
    const tmdbId2 = context.media.tmdbId;
    if (!tmdbId2) {
        throw new ScraperError("No TMDB ID found");
    }
    const value = vidlinkProcessData2(tmdbId2);
    const requestOptions = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
        Referer: "https://vidlink.pro/",
        Origin: "https://vidlink.pro"
    };
    const requestOptions2 = {
        baseUrl: vidlinkBaseUrl,
        headers: requestOptions
    };
    const response = await context.proxiedFetcher("/api/b/movie/" + value + "?multiLang=0", requestOptions2);
    const data = typeof response
        === "string"
        ? JSON.parse(response) : response;
    if (!data || !data.stream || !data.stream.playlist) {
        throw new ScraperError("No stream found");
    }
    const playlistUrl = data.stream.playlist;
    let language = ((temporaryValue = data.stream.captions) == null ? void 0 : temporaryValue.map(item => {
        const language = normalizeLanguageCode(item.language);
        return language ? { id: item.id || item.url, url: item.url, language: language, type: item.type
                === "vtt"
                ? "vtt" : "srt", hasCorsRestrictions: item.hasCorsRestrictions ?? false } : null;
    }).filter(item => item !== null)) || [];
    language = deduplicateCaptionsByLanguage(language);
    return { stream: [{ id: "primary", type: "hls", playlist: vidlinkBuildRequestUrl(playlistUrl), flags: ["cors-allowed"], captions: language }], embeds: [] };
}
async function scrapeVidlinkShow(context) {
    var temporaryValue;
    const tmdbId2 = context.media.tmdbId;
    if (!tmdbId2) {
        throw new ScraperError("No TMDB ID found");
    }
    const value = vidlinkProcessData2(tmdbId2);
    const requestOptions = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
        Referer: "https://vidlink.pro/",
        Origin: "https://vidlink.pro"
    };
    const requestOptions2 = {
        baseUrl: vidlinkBaseUrl,
        headers: requestOptions
    };
    const response = await context.proxiedFetcher("/api/b/tv/" + value + "/" + context.media.season.number + "/" + context.media.episode.number + "?multiLang=0", requestOptions2);
    const data = typeof response
        === "string"
        ? JSON.parse(response) : response;
    if (!data || !data.stream || !data.stream.playlist) {
        throw new ScraperError("No stream found");
    }
    const playlistUrl = data.stream.playlist;
    let language = ((temporaryValue = data.stream.captions) == null ? void 0 : temporaryValue.map(item => {
        const language = normalizeLanguageCode(item.language);
        return language ? { id: item.id || item.url, url: item.url, language: language, type: item.type
                === "vtt"
                ? "vtt" : "srt", hasCorsRestrictions: item.hasCorsRestrictions ?? false } : null;
    }).filter(item => item !== null)) || [];
    language =
        deduplicateCaptionsByLanguage(language);
    return { stream: [{ id: "primary", type: "hls", playlist: vidlinkBuildRequestUrl(playlistUrl), flags: ["cors-allowed"], captions: language }], embeds: [] };
}
const vidlinkProviderConfig = {
    id: "vidlink",
    name: "KingLink \uD83D\uDD25",
    rank: 873,
    flags: ["cors-allowed"],
    scrapeMovie: scrapeVidlinkMovie,
    scrapeShow: scrapeVidlinkShow,
    disabled: false
};
const vidlinkProvider = createSourceProvider(vidlinkProviderConfig);
const vidrockValue = "x7k9mPqT2rWvY8zA5bC3nF6hJ2lK4mN9";
const vidrockValue2 = CryptoJS.enc.Utf8.parse(vidrockValue);
const vidrockValue3 = CryptoJS.lib.WordArray.create(vidrockValue2.words.slice(0, 4));
const vidrockBaseUrl = "https://vidrock.net";
const vidrockValue4 = "Mozilla/5.0 (Linux; Android 10; K) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/137.0.0.0 Mobile Safari/537.36";
async function scrapeVidrock(context) {
    var temporaryValue;
    var url;
    const type2 = context.media.type;
    let temporaryValue4;
    type2 === "movie" ? temporaryValue4 = context.media.tmdbId : temporaryValue4 = context.media.tmdbId + "_" + context.media.season.number + "_" + context.media.episode.number;
    const token = CryptoJS.AES.encrypt(temporaryValue4, vidrockValue2, { iv: vidrockValue3, mode: CryptoJS.mode.CBC, padding: CryptoJS.pad.Pkcs7 });
    const value = encodeURIComponent(token.toString());
    const requestUrl = vidrockBaseUrl + "/api/" + type2 + "/" + value;
    const requestOptions = {
        Referer: vidrockBaseUrl,
        "User-Agent": vidrockValue4
    };
    const requestOptions2 = {
        headers: requestOptions
    };
    const response = await context.proxiedFetcher(requestUrl, requestOptions2);
    if (!response || typeof response !== "object") {
        throw new ScraperError("No sources found from Vidrock API: Invalid response");
    }
    const streams = [];
    if ((temporaryValue = response.Nova) != null && temporaryValue.url) {
        const embed = {
            embedId: "vidrock-nova",
            url: response.Nova.url
        };
        streams.push(embed);
    }
    if ((url = response.Luna) != null && url.url) {
        const embed3 = {
            embedId: "vidrock-luna",
            url: response.Luna.url
        };
        streams.push(embed3);
    }
    if (streams.length === 0) {
        throw new ScraperError("No valid sources found from Vidrock API");
    }
    return {
        embeds: streams
    };
}
const vidrockProviderConfig = {
    id: "vidrock",
    name: "Granite \uD83E\uDEA8",
    rank: 780,
    disabled: true,
    flags: ["cors-allowed"],
    scrapeMovie: scrapeVidrock,
    scrapeShow: scrapeVidrock
};
const vidrockProvider = createSourceProvider(vidrockProviderConfig);
async function scrapeVidzee(context) {
    const value = { type: context.media.type, title: context.media.title, tmdbId: context.media.tmdbId, imdbId: context.media.imdbId, ...context.media.type === "show" && { season: context.media.season.number, episode: context.media.episode.number }, releaseYear: context.media.releaseYear };
    const results = [{ embedId: "vidzee-server1", url: JSON.stringify(value) }, { embedId: "vidzee-server2", url: JSON.stringify(value) }];
    return {
        embeds: results
    };
}
const vidzeeProviderConfig = {
    id: "vidzee",
    name: "Vidzee \uD83D\uDC1D",
    rank: 180,
    disabled: true,
    flags: ["cors-allowed"],
    scrapeMovie: scrapeVidzee,
    scrapeShow: scrapeVidzee
};
const vidzeeProvider = createSourceProvider(vidzeeProviderConfig);
async function warezcdnBuildRequestUrl(context, argument2, argument3) {
    const results = [];
    for (const item of argument2.split(",")) {
        const result = {
            id: context,
            sv: item
        };
        const result2 = {
            id: context,
            sv: item
        };
        await argument3.proxiedFetcher("/getEmbed.php", { baseUrl: warezcdnEmbedBaseUrl, headers: { Referer: warezcdnEmbedBaseUrl + "/getEmbed.php?" + new URLSearchParams(result) }, method: "HEAD", query: result2 });
        const result3 = {
            id: context,
            sv: item
        };
        const result4 = {
            id: context,
            sv: item
        };
        const response = await argument3.proxiedFetcher("/getPlay.php", { baseUrl: warezcdnEmbedBaseUrl, headers: { Referer: warezcdnEmbedBaseUrl + "/getEmbed.php?" + new URLSearchParams(result3) }, query: result4 });
        const match = response.match(/window.location.href\s*=\s*"([^"]+)"/)?.[1];
        if (match &&
            item === "warezcdn") {
            const embed = {
                embedId: warezcdnembedhlsEmbedProvider.id,
                url: match
            };
            const embed4 = {
                embedId: warezcdnembedmp4EmbedProvider.id,
                url: match
            };
            const embed5 = {
                embedId: warezplayerEmbedProvider.id,
                url: match
            };
            results.push(embed, embed4, embed5);
        }
        else {
            match && item === "mixdrop" && results.push({ embedId: mixdropEmbedProvider.id, url: match });
        }
    }
    return {
        embeds: results
    };
}
async function scrapeWarezcdnMovie(context) {
    if (!context.media.imdbId) {
        throw new ScraperError("This source requires IMDB id.");
    }
    const result = {
        baseUrl: warezcdnEmbedBaseUrl
    };
    const response = await context.proxiedFetcher("/filme/" + context.media.imdbId, result);
    const [, itemValue, itemValue2] = response.match(/let\s+data\s*=\s*'\[\s*\{\s*"id":"([^"]+)".*?"servers":"([^"]+)"/);
    if (!itemValue
        ||
            !itemValue2) {
        throw new ScraperError("Failed to find episode id");
    }
    context.progress(40);
    return warezcdnBuildRequestUrl(itemValue, itemValue2, context);
}
const warezcdnSourceProvider = createSourceProvider({ id: "warezcdn", name: "WarezCDN", disabled: true, rank: 115, flags: [], scrapeMovie: scrapeWarezcdnMovie });
const webtorServerUrls = ["udp://tracker.opentrackr.org:1337/announce", "udp://open.demonii.com:1337/announce", "udp://open.tracker.cl:1337/announce", "udp://open.stealth.si:80/announce", "udp://tracker.torrent.eu.org:451/announce", "udp://explodie.org:6969/announce", "udp://tracker.qu.ax:6969/announce", "udp://tracker.ololosh.space:6969/announce", "udp://tracker.dump.cl:6969/announce", "udp://tracker.dler.org:6969/announce", "udp://tracker.bittor.pw:1337/announce", "udp://tracker-udp.gbitt.info:80/announce", "udp://opentracker.io:6969/announce", "udp://open.free-tracker.ga:6969/announce", "udp://ns-1.x-fins.com:6969/announce", "udp://leet-tracker.moe:1337/announce", "udp://isk.richardsw.club:6969/announce", "udp://discord.heihachi.pw:6969/announce", "http://www.torrentsnipe.info:2701/announce", "http://www.genesis-sp.org:2710/announce"];
function webtorProcessData(input, argument2) {
    const value = encodeURIComponent(argument2);
    const items = webtorServerUrls.map(item => "&tr=" + encodeURIComponent(item)).join("");
    return "magnet:?xt=urn:btih:" + input + "&dn=" + value + items;
}
function webtorProcessData2(input) {
    const value = encodeURIComponent(input);
    return "cors.aether.mom/?destination=https://savingshub.online/api/fetchHls?magnet=" + value;
}
function webtorMapQuality(input) {
    const result = {
        "4k": [],
        "1080p": [],
        "720p": [],
        "480p": []
    };
    const value = result;
    input.forEach(item => {
        const normalizedValue = item.name.toLowerCase();
        if (normalizedValue.includes("4k")) {
            value["4k"].push(item);
        }
        else if (normalizedValue.includes("1080p")) {
            value["1080p"].push(item);
        }
        else if (normalizedValue.includes("720p")) {
            ;
            value["720p"].push(item);
        }
        else if (normalizedValue.includes("480p")) {
            ;
            value["480p"].push(item);
        }
    });
    return value;
}
function webtorExtractValue(input, argument2) {
    return input.sort((left, right) => {
        ;
        {
            const match = parseInt((left.title.match(/👤 (\d+) /)?.[1]) || "0", 10);
            const match3 = parseInt((right.title.match(/👤 (\d+) /)?.[1]) || "0", 10);
            return match3 - match;
        }
    }).slice(0, argument2);
}
async function scrapeWebtor(context) {
    const value = context.media.type === "movie" ? "movie/" + context.media.imdbId + ".json" : "series/" + context.media.imdbId + ":" + context.media.season.number + ":" + context.media.episode.number + ".json";
    const response = await context.fetcher("https://torrentio.strem.fun/providers=yts,eztv,rarbg,1337x,thepiratebay,kickasstorrents,torrentgalaxy,magnetdl,horriblesubs,nyaasi,tokyotosho,anidex/stream/" + value).then(argument1 => typeof argument1 == "string" ? JSON.parse(argument1) : argument1);
    context.progress(50);
    const value3 = webtorMapQuality(response.streams);
    const results = [];
    (await Promise.all(Object.entries(value3).map(async ([s, u]) => {
        const [itemValue] = webtorExtractValue(u, 1);
        if (!itemValue) {
            return null;
        }
        try {
            {
                const value = webtorProcessData(itemValue.infoHash, itemValue.name);
                const value5 = webtorProcessData2(value);
                const response = await context.fetcher(value5);
                const parsedData = typeof response
                    === "string"
                    ? JSON.parse(response) : response;
                if (!(parsedData != null && parsedData.m3u8Link)) {
                    throw new Error("No m3u8 link in response");
                }
                return {
                    quality: s,
                    url: parsedData.m3u8Link
                };
            }
        }
        catch (error2) {
            console.error("Failed to fetch " + s + ":", error2);
            return null;
        }
    }))).forEach(item => {
        if (item != null && item.url) {
            results.push({ embedId: "webtor-" + item.quality.replace("p", ""), url: item.url });
        }
    });
    context.progress(90);
    return {
        embeds: results
    };
}
const webtorProviderConfig = {
    id: "webtor",
    name: "Webtor \uD83E\uDDA5",
    rank: 2,
    disabled: true,
    flags: ["cors-allowed"],
    scrapeMovie: scrapeWebtor,
    scrapeShow: scrapeWebtor
};
const webtorProvider = createSourceProvider(webtorProviderConfig);
const wecimaBaseUrl = "https://wecima.tube";
async function scrapeWecima(context) {
    const result = {
        baseUrl: wecimaBaseUrl
    };
    const response = await context.proxiedFetcher("/search/" + encodeURIComponent(context.media.title) + "/", result);
    const document = loadHtml(response);
    const value = document(".Grid--WecimaPosts .GridItem a").first();
    if (!value.length) {
        throw new ScraperError("No results found");
    }
    const url = value.attr("href");
    if (!url) {
        throw new ScraperError("No content URL found");
    }
    context.progress(30);
    const requestOptions3 = {
        baseUrl: wecimaBaseUrl
    };
    const response2 = await context.proxiedFetcher(url, requestOptions3);
    const document6 = loadHtml(response2);
    let temporaryValue;
    if (context.media.type === "movie") {
        temporaryValue = document6("meta[itemprop=\"embedURL\"]").attr("content");
    }
    else {
        const url3 = document6(".List--Seasons--Episodes a");
        let url4;
        for (const item of url3)
            if (document6(item).text().trim().includes("\u0645\u0648\u0633\u0645 " + context.media.season)) {
                url4 = document6(item).attr("href");
                break;
            }
        if (!url4) {
            throw new ScraperError("Season " + context.media.season + " not found");
        }
        const requestOptions4 = {
            baseUrl: wecimaBaseUrl
        };
        const response3 = await context.proxiedFetcher(url4, requestOptions4);
        const document7 = loadHtml(response3);
        const url5 = document7(".Episodes--Seasons--Episodes a");
        for (const temporaryValue4 of url5)
            if (document7(temporaryValue4).find("episodetitle").text().trim() === "\u0627\u0644\u062D\u0644\u0642\u0629 " + context.media.episode) {
                const url6 = document7(temporaryValue4).attr("href");
                if (url6) {
                    const requestOptions5 = {
                        baseUrl: wecimaBaseUrl
                    };
                    const response4 = await context.proxiedFetcher(url6, requestOptions5);
                    const document8 = loadHtml(response4);
                    temporaryValue = document8("meta[itemprop=\"embedURL\"]").attr("content");
                }
                break;
            }
    }
    if (!temporaryValue) {
        throw new ScraperError("No embed URL found");
    }
    context.progress(60);
    const response5 = await context.proxiedFetcher(temporaryValue);
    const document9 = loadHtml(response5);
    const url7 = document9("source[type=\"video/mp4\"]").attr("src");
    if (!url7) {
        throw new ScraperError("No video source found");
    }
    context.progress(90);
    const requestOptions = {
        referer: wecimaBaseUrl
    };
    const stream = {
        type: "mp4",
        url: url7
    };
    const stream3 = {
        unknown: stream
    };
    const requestOptions2 = {
        id: "primary",
        type: "file",
        flags: [],
        headers: requestOptions,
        qualities: stream3,
        captions: []
    };
    return {
        embeds: [],
        stream: [requestOptions2]
    };
}
const wecimaProviderConfig = {
    id: "wecima",
    name: "Wecima \uD83C\uDF5B",
    rank: 3,
    disabled: true,
    flags: [],
    scrapeMovie: scrapeWecima,
    scrapeShow: scrapeWecima
};
const wecimaProvider = createSourceProvider(wecimaProviderConfig);
const xpassBaseUrl = "https://play.xpass.top";
async function xpassExtractValue(context) {
    const value = context.media.type === "movie" ? xpassBaseUrl + "/e/movie/" + context.media.tmdbId + "?autostart=true" : xpassBaseUrl + "/e/tv/" + context.media.tmdbId + "/" + context.media.season.number + "/" + context.media.episode.number + "?autostart=true";
    const response = await context.proxiedFetcher(value);
    const match = response.match(/var\s+backups\s*=\s*(\[.*?\])(?:;|<\/script>)/s);
    if (!match) {
        throw new ScraperError("No backups found in XPass response");
    }
    let results = [];
    try {
        results = JSON.parse(match[1]);
    }
    catch {
        throw new ScraperError("Failed to parse XPass backups");
    }
    const embeds = [];
    const result = {};
    const result2 = {};
    for (const item of results) {
        if (!item.name) {
            continue;
        }
        const value9 = item.name.toUpperCase();
        let value10 = "";
        value9.includes("FIL") ? value10 = "fil" : value9.includes("DOO") ? value10 = "doo" : value9.includes("WIS") ? value10 = "wis" : value9.includes("VSR") ? value10 = "vsr" : value9.includes("VXR") ? value10 = "vxr" : value9.includes("VRK") ? value10 = "vrk" : value9.includes("MIX") ? value10 = "mix" : value9.includes("LUL") ? value10 = "lul" : value9.includes("MOL") ? value10 = "mol" : value9.includes("MEG") ? value10 = "meg" : value9.includes("MOV") ? value10 = "mov" : value9.includes("SFY") ? value10 = "sfy" : value9.includes("BIG") ? value10 = "big" : value9.includes("VOE") && (value10 = "voe");
        value10 && (result[value10] =
            (result[value10] || 0)
                +
                    1);
    }
    for (const temporaryValue of results) {
        if (!temporaryValue.url || !temporaryValue.name) {
            continue;
        }
        const value11 = temporaryValue.name.toUpperCase();
        let value12 = "";
        if (value11.includes("FIL") ? value12 = "fil" : value11.includes("DOO") ? value12 = "doo" : value11.includes("WIS") ? value12 = "wis" : value11.includes("VSR") ? value12 = "vsr" : value11.includes("VXR") ? value12 = "vxr" : value11.includes("VRK") ? value12 = "vrk" : value11.includes("MIX") ? value12 = "mix" : value11.includes("LUL") ? value12 = "lul" : value11.includes("MOL") ? value12 = "mol" : value11.includes("MEG") ? value12 = "meg" : value11.includes("MOV") ? value12 = "mov" : value11.includes("SFY") ? value12 = "sfy" : value11.includes("BIG") ? value12 = "big" : value11.includes("VOE") && (value12 = "voe"), !value12) {
            continue;
        }
        result2[value12] =
            (result2[value12] || 0)
                +
                    1;
        const value13 = result[value12];
        const value14 = result2[value12];
        let value15 = "xpass-" + value12;
        value13 > 1 && (value15 = "xpass-" + value12 + "-" + value14);
        embeds.push({ embedId: value15, url: temporaryValue.url.startsWith("http") ? temporaryValue.url : "" + xpassBaseUrl + temporaryValue.url });
    }
    return embeds;
}
async function scrapeXpassMovie(context) {
    return ({ embeds: await xpassExtractValue(context) });
}
async function scrapeXpassShow(context) {
    return ({ embeds: await xpassExtractValue(context) });
}
const xpassSourceProvider = createSourceProvider({ id: "xpass", name: "Psuedo \uD83D\uDC7D", rank: 900, disabled: false, flags: ["cors-allowed"], scrapeMovie: scrapeXpassMovie, scrapeShow: scrapeXpassShow });
async function scrapeXprimetv(context) {
    const value = { type: context.media.type, title: context.media.title, tmdbId: context.media.tmdbId, imdbId: context.media.imdbId, ...context.media.type === "show" && { season: context.media.season.number, episode: context.media.episode.number }, releaseYear: context.media.releaseYear };
    return { embeds: [{ embedId: "xprime-rage", url: JSON.stringify(value) }, { embedId: "xprime-apollo", url: JSON.stringify(value) }, { embedId: "xprime-streambox", url: JSON.stringify(value) }, { embedId: "xprime-fox", url: JSON.stringify(value) }, { embedId: "xprime-primenet", url: JSON.stringify(value) }, { embedId: "xprime-kraken", url: JSON.stringify(value) }, { embedId: "xprime-phoenix", url: JSON.stringify(value) }, { embedId: "xprime-harbour", url: JSON.stringify(value) }, { embedId: "xprime-fendi", url: JSON.stringify(value) }, { embedId: "xprime-marant", url: JSON.stringify(value) }, { embedId: "xprime-volkswagen", url: JSON.stringify(value) }] };
}
const xprimetvProviderConfig = {
    id: "xprimetv",
    name: "XPrime \uD83D\uDCA3",
    rank: 244,
    disabled: true,
    flags: ["cors-allowed"],
    scrapeMovie: scrapeXprimetv,
    scrapeShow: scrapeXprimetv
};
const xprimetvProvider = createSourceProvider(xprimetvProviderConfig);
async function scrapeZunimeShow(context) {
    const value = await fsharetvLookupEpisode(context, context.media);
    const result = {
        episode: 1
    };
    const result2 = { type: context.media.type, title: context.media.title, tmdbId: context.media.tmdbId, imdbId: context.media.imdbId, anilistId: value, ...context.media.type === "show" && { season: context.media.season.number, episode: context.media.episode.number }, ...context.media.type === "movie" && result, releaseYear: context.media.releaseYear };
    return { embeds: [{ embedId: "zunime-hd-2", url: JSON.stringify(result2) }, { embedId: "zunime-miko", url: JSON.stringify(result2) }, { embedId: "zunime-shiro", url: JSON.stringify(result2) }, { embedId: "zunime-zaza", url: JSON.stringify(result2) }] };
}
const zunimeProviderConfig = {
    id: "zunime",
    name: "Zunime \u26E9\uFE0F",
    rank: 125,
    disabled: true,
    flags: ["cors-allowed"],
    scrapeShow: scrapeZunimeShow
};
const zunimeProvider = createSourceProvider(zunimeProviderConfig);

require("./anisurgeProviders").registerAnisurgeProviders({
  createSourceProvider,
  ScraperError,
  lookupAnilistId: fsharetvLookupEpisode,
});

function createDefaultRunner(options = {}) {
    return createScraperRunner({
        sources: registeredSources,
        embeds: registeredEmbeds,
        features: options.features ?? { requires: ["cors-allowed"], disallowed: [] },
        fetcher: options.fetcher,
        proxiedFetcher: options.proxiedFetcher ?? options.fetcher,
        proxyStreams: options.proxyStreams ?? false,
    });
}

module.exports = {
    ScraperError,
    setProxyBaseUrl,
    createSourceProvider,
    createEmbedProvider,
    createScraperRunner,
    createDefaultRunner,
    registeredSources,
    registeredEmbeds,
    listSourceMetadata,
    listEmbedMetadata,
    getProviderMetadata,
    loadHtml,
    normalizeFetcher,
    supportsRequiredFlags,
};
