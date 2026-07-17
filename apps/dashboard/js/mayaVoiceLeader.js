/**
 * VOICE-005: one mic/playback leader per browser profile.
 * Prefers Web Locks; falls back to BroadcastChannel heartbeat election.
 */
(function () {
  "use strict";

  const LOCK_NAME = "maya-voice-audio-leader";
  const CHANNEL = "maya-voice-leader-v1";
  const HEARTBEAT_MS = 2000;
  const STALE_MS = 5000;

  const tabId =
    typeof crypto !== "undefined" && crypto.randomUUID
      ? crypto.randomUUID()
      : `t_${Date.now()}_${Math.random().toString(16).slice(2)}`;

  let isLeader = false;
  let stopped = false;
  let subscriberId = null;
  let claimTimer = null;
  const listeners = new Set();
  const peers = new Map(); // tabId -> lastSeen

  function notify() {
    for (const fn of listeners) {
      try {
        fn(isLeader);
      } catch (_) {}
    }
  }

  function setLeader(next) {
    if (isLeader === next) return;
    isLeader = next;
    notify();
    scheduleLeaderClaim();
    if (isLeader) {
      window.mayaBrowserMic?.onBecameLeader?.();
      window.mayaBrowserAudioOutput?.onBecameLeader?.();
    } else {
      window.mayaBrowserMic?.onLostLeadership?.();
      window.mayaBrowserAudioOutput?.onLostLeadership?.();
    }
  }

  function scheduleLeaderClaim() {
    if (claimTimer) clearTimeout(claimTimer);
    claimTimer = setTimeout(() => {
      claimTimer = null;
      claimAudioLeadership().catch(() => {});
    }, 50);
  }

  async function claimAudioLeadership() {
    if (!subscriberId) return;
    try {
      await fetch("/api/voice/agent/audio-leader", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          subscriber_id: subscriberId,
          leader: !!isLeader,
        }),
      });
    } catch (_) {}
  }

  function electFromPeers() {
    peers.set(tabId, Date.now());
    const now = Date.now();
    let winner = tabId;
    for (const [id, seen] of peers) {
      if (now - seen > STALE_MS) {
        peers.delete(id);
        continue;
      }
      if (id < winner) winner = id;
    }
    setLeader(winner === tabId);
  }

  function startBroadcastFallback() {
    if (typeof BroadcastChannel === "undefined") {
      // Last resort: this tab leads (single-tab browsers without BC/locks).
      setLeader(true);
      return;
    }
    const bc = new BroadcastChannel(CHANNEL);
    const beat = () => {
      if (stopped) return;
      bc.postMessage({ type: "heartbeat", tabId, ts: Date.now() });
      electFromPeers();
    };
    bc.onmessage = (ev) => {
      const data = ev.data || {};
      if (data.type === "heartbeat" && data.tabId) {
        peers.set(data.tabId, Number(data.ts) || Date.now());
        electFromPeers();
      } else if (data.type === "bye" && data.tabId) {
        peers.delete(data.tabId);
        electFromPeers();
      }
    };
    beat();
    const iv = setInterval(beat, HEARTBEAT_MS);
    window.addEventListener(
      "pagehide",
      () => {
        stopped = true;
        clearInterval(iv);
        try {
          bc.postMessage({ type: "bye", tabId });
          bc.close();
        } catch (_) {}
        setLeader(false);
      },
      { once: true },
    );
  }

  function startWebLocks() {
    const run = () => {
      if (stopped || !navigator.locks?.request) return;
      navigator.locks
        .request(LOCK_NAME, async () => {
          setLeader(true);
          await new Promise((resolve) => {
            window.addEventListener("pagehide", resolve, { once: true });
          });
          setLeader(false);
        })
        .catch(() => {})
        .finally(() => {
          if (!stopped) queueMicrotask(run);
        });
    };
    run();
  }

  function start() {
    if (navigator.locks?.request) startWebLocks();
    else startBroadcastFallback();
  }

  window.mayaVoiceLeader = {
    tabId,
    isLeader() {
      return isLeader;
    },
    onChange(fn) {
      if (typeof fn !== "function") return () => {};
      listeners.add(fn);
      try {
        fn(isLeader);
      } catch (_) {}
      return () => listeners.delete(fn);
    },
    setSubscriberId(id) {
      subscriberId = id || null;
      scheduleLeaderClaim();
    },
    /** Test helper — force leadership without locks. */
    _forceLeaderForTests(next) {
      setLeader(!!next);
    },
  };

  start();
})();
