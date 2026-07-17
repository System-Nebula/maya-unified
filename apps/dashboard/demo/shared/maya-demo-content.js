/** Shared mock content covering Maya companion / memory / settings surfaces. */
(function (global) {
  const brands = [
    { slug: "elevenlabs", label: "ElevenLabs", tone: "warm" },
    { slug: "linear", label: "Linear", tone: "dense" },
    { slug: "raycast", label: "Raycast", tone: "dense" },
    { slug: "cursor", label: "Cursor", tone: "dense" },
    { slug: "voltagent", label: "VoltAgent", tone: "dense" },
    { slug: "spotify", label: "Spotify", tone: "warm" },
    { slug: "vercel", label: "Vercel", tone: "dense" },
    { slug: "supabase", label: "Supabase", tone: "dense" },
    { slug: "resend", label: "Resend", tone: "dense" },
    { slug: "stripe", label: "Stripe", tone: "warm" },
    { slug: "ollama", label: "Ollama", tone: "dense" },
    { slug: "sentry", label: "Sentry", tone: "dense" },
  ];

  const companion = {
    status: [
      { label: "Agent", value: "ready", ok: true },
      { label: "LLM", value: "qwen3-8b", ok: true },
      { label: "Voice", value: "listening", ok: true },
      { label: "Vision", value: "idle", ok: false },
    ],
    messages: [
      {
        role: "user",
        text: "Hey Maya — queue something chill and tell me what’s on my calendar.",
        meta: "voice · 1.2s STT",
      },
      {
        role: "ai",
        text: "Queued Night Drive Radio. You’ve got standup at 10:30 and a design review at 2.",
        meta: "tools · calendar.list · dashboard_start_radio · 840ms TTS",
      },
      {
        role: "user",
        text: "Check the screen and describe what I’m looking at.",
        meta: "typed",
      },
      {
        role: "ai",
        text: "Looks like a VS Code window on maya-unified with the conversation hub open.",
        meta: "vision · screen_frame · 1.1s",
      },
    ],
    queue: [
      { title: "Night Drive", artist: "Radio · Maya", dur: "∞" },
      { title: "Ceramic Bloom", artist: "Lo-fi Room", dur: "3:42" },
      { title: "Signal Soft", artist: "Analog Coast", dur: "4:05" },
    ],
    tools: [
      { t: "12:04:01", name: "dashboard_start_radio", detail: "query=chill night drive" },
      { t: "12:04:02", name: "calendar.list", detail: "today · 2 events" },
      { t: "12:04:18", name: "vision.describe", detail: "screen_frame ok" },
      { t: "12:04:19", name: "mcp.filesystem", detail: "skipped · not needed" },
    ],
    cmds: ["/play", "/imagine", "/memory", "/discord", "/status", "/help"],
    imagine: [
      { label: "A", prompt: "neon rain alley, cinematic", votes: 3 },
      { label: "B", prompt: "neon rain alley, softer fog", votes: 5 },
    ],
    extras: [
      { title: "Rooms", body: "Public / private voice rooms with share links." },
      { title: "Game Mode", body: "mGBA bridge + capture — in product, demos only." },
      { title: "OBS Overlay", body: "Transparent VRM overlay for streams." },
    ],
  };

  const memory = {
    profile: {
      name: "Jovan",
      timezone: "America/Denver",
      notes: "Prefers short spoken replies. Heavy music + coding context.",
    },
    facts: [
      { text: "Works on Maya Unified voice companion", importance: 5, when: "2d ago" },
      { text: "Likes lo-fi and night-drive radio while coding", importance: 4, when: "5d ago" },
      { text: "Uses Discord for music cast and bot replies", importance: 4, when: "1w ago" },
      { text: "Prefers Whisper STT on local RTX", importance: 3, when: "3d ago" },
    ],
    skills: [
      { name: "morning_brief", desc: "Calendar + weather + first playlist" },
      { name: "screen_coach", desc: "Describe screen and suggest next step" },
      { name: "dj_mode", desc: "Radio + Discord cast helpers" },
    ],
    approvals: [
      { text: "Remember: standup is usually 10:30", source: "conversation" },
      { text: "Favorite TTS voice: warm mid", source: "settings" },
    ],
    searchHits: [
      { title: "Night drive playlist request", when: "Today", snippet: "queue something chill…" },
      { title: "Vision false-positive Discord fix", when: "Yesterday", snippet: "again and tell me…" },
    ],
    adminTeaser: [
      { ws: "default", kind: "semantic", rows: 1284 },
      { ws: "default", kind: "notes", rows: 42 },
      { ws: "lab", kind: "cognitive", rows: 19 },
    ],
  };

  const settingsBuckets = [
    {
      id: "you",
      label: "You",
      tabs: [
        {
          id: "profile",
          label: "Profile",
          fields: [
            { label: "Display name", value: "Jovan", type: "text" },
            { label: "Email", value: "admin@local", type: "text" },
            { label: "Detailed transcripts", value: "on", type: "select", options: ["on", "off"] },
          ],
        },
        {
          id: "personality",
          label: "Personality",
          fields: [
            { label: "Active card", value: "Maya · Warm Operator", type: "text" },
            { label: "Style", value: "concise, friendly, technical", type: "textarea" },
          ],
        },
      ],
    },
    {
      id: "sound",
      label: "Sound",
      tabs: [
        {
          id: "audio",
          label: "Audio",
          fields: [
            { label: "Output volume", value: "80", type: "text" },
            { label: "EQ preset", value: "Voice Presence", type: "select", options: ["Flat", "Voice Presence", "Bass Lift"] },
            { label: "AEC", value: "on", type: "select", options: ["on", "off"] },
          ],
        },
        {
          id: "detection",
          label: "Detection",
          fields: [
            { label: "Mode", value: "VAD", type: "select", options: ["VAD", "PTT", "Continuous"] },
            { label: "Barge-in", value: "on", type: "select", options: ["on", "off"] },
          ],
        },
        {
          id: "voice",
          label: "Voice",
          fields: [
            { label: "TTS speaker", value: "maya-warm", type: "text" },
            { label: "Clone ref", value: "refs/warm.wav", type: "text" },
          ],
        },
        {
          id: "delivery",
          label: "Delivery",
          fields: [
            { label: "TTS mode", value: "stream", type: "select", options: ["stream", "batch"] },
            { label: "Instruct", value: "calm, clear, short", type: "textarea" },
          ],
        },
        {
          id: "dictation",
          label: "Dictation",
          fields: [
            { label: "Backend", value: "whisper · distil-large-v3", type: "text" },
            { label: "Wispr", value: "off", type: "select", options: ["on", "off"] },
          ],
        },
      ],
    },
    {
      id: "look",
      label: "Look",
      tabs: [
        {
          id: "expressions",
          label: "Expressions / VRM",
          fields: [
            { label: "Model", value: "maya-default.vrm", type: "text" },
            { label: "Lip-sync", value: "on", type: "select", options: ["on", "off"] },
            { label: "Idle pool", value: "mixamo-soft", type: "text" },
            { label: "VTube Studio", value: "optional", type: "text" },
          ],
        },
      ],
    },
    {
      id: "mind",
      label: "Mind",
      tabs: [
        {
          id: "reasoning",
          label: "Reasoning",
          fields: [
            { label: "Backend", value: "LM Studio", type: "select", options: ["LM Studio", "LiteLLM", "WebLLM"] },
            { label: "Chat model", value: "qwen3-8b", type: "text" },
            { label: "Vision model", value: "qwen2.5-vl", type: "text" },
          ],
        },
        {
          id: "memory",
          label: "Memory prefs",
          fields: [
            { label: "Semantic memory", value: "on", type: "select", options: ["on", "off"] },
            { label: "Write approval", value: "required", type: "select", options: ["required", "auto"] },
            { label: "Prefetch", value: "on", type: "select", options: ["on", "off"] },
          ],
        },
      ],
    },
    {
      id: "powers",
      label: "Powers",
      tabs: [
        {
          id: "tools",
          label: "Tools",
          fields: [
            { label: "Tools enabled", value: "on", type: "select", options: ["on", "off"] },
            { label: "Max rounds", value: "6", type: "text" },
            { label: "MCP servers", value: "2 connected", type: "text" },
          ],
        },
        {
          id: "imagine",
          label: "Imagine",
          fields: [
            { label: "ComfyUI", value: "online", type: "text" },
            { label: "Default workflow", value: "maya-sdxl", type: "text" },
          ],
        },
        {
          id: "integrations",
          label: "Integrations",
          fields: [
            { label: "Google", value: "Gmail + Calendar", type: "text" },
            { label: "Bandcamp", value: "wishlist linked", type: "text" },
          ],
        },
        {
          id: "discord",
          label: "Discord",
          fields: [
            { label: "Bot", value: "online", type: "text" },
            { label: "VC listen", value: "on", type: "select", options: ["on", "off"] },
            { label: "Music cast", value: "on", type: "select", options: ["on", "off"] },
          ],
        },
      ],
    },
    {
      id: "platform",
      label: "Platform",
      tabs: [
        {
          id: "platform",
          label: "Platform",
          fields: [
            { label: "DB URL", value: "sqlite:///maya.db", type: "text" },
            { label: "OTEL", value: "off", type: "select", options: ["on", "off"] },
          ],
        },
        {
          id: "admin",
          label: "Admin",
          fields: [
            { label: "Users", value: "3 operators", type: "text" },
            { label: "Workspaces", value: "default, lab", type: "text" },
          ],
        },
      ],
    },
  ];

  global.MayaDemo = {
    brands,
    companion,
    memory,
    settingsBuckets,
  };
})(window);
