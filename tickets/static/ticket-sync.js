/** Cross-tab ticket status sync (board ↔ detail). */
(function (global) {
  const CHANNEL = "sme-ticket-sync";
  const STORAGE_KEY = "sme-ticket-sync-event";

  function publish(payload) {
    const message = Object.assign({ ts: Date.now() }, payload || {});
    try {
      if (typeof BroadcastChannel !== "undefined") {
        const bc = new BroadcastChannel(CHANNEL);
        bc.postMessage(message);
        bc.close();
      }
    } catch (_err) {
      /* ignore */
    }
    try {
      localStorage.setItem(STORAGE_KEY, JSON.stringify(message));
      localStorage.removeItem(STORAGE_KEY);
    } catch (_err) {
      /* ignore */
    }
  }

  function subscribe(handler) {
    let bc = null;
    try {
      if (typeof BroadcastChannel !== "undefined") {
        bc = new BroadcastChannel(CHANNEL);
        bc.onmessage = (event) => handler(event.data || {});
      }
    } catch (_err) {
      bc = null;
    }
    function onStorage(event) {
      if (event.key !== STORAGE_KEY || !event.newValue) return;
      try {
        handler(JSON.parse(event.newValue));
      } catch (_err) {
        /* ignore */
      }
    }
    window.addEventListener("storage", onStorage);
    return function unsubscribe() {
      window.removeEventListener("storage", onStorage);
      if (bc) {
        try {
          bc.close();
        } catch (_err) {
          /* ignore */
        }
      }
    };
  }

  global.TicketSync = { publish, subscribe, CHANNEL, STORAGE_KEY };
})(window);
