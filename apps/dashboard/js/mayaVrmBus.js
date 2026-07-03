/** BroadcastChannel bridge between dashboard embed and VRM pop-out window. */
const CHANNEL = "maya-vrm-v1";

export function createVrmBus() {
  if (typeof BroadcastChannel === "undefined") {
    return {
      post() {},
      on() {},
      close() {},
    };
  }
  const bc = new BroadcastChannel(CHANNEL);
  return {
    post(msg) {
      try {
        bc.postMessage(msg);
      } catch (_) {}
    },
    on(fn) {
      bc.onmessage = (e) => {
        try {
          fn(e.data);
        } catch (_) {}
      };
    },
    close() {
      bc.close();
    },
  };
}

export function isPopoutPage() {
  return /\/avatar\/popout/.test(window.location.pathname);
}
