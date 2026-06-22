/*
 * tauri-bridge.js — Windows shim that emulates the macOS WebKit native bridge
 * on top of Tauri, so the shared frontend (report.js) runs UNCHANGED.
 *
 * report.js detects the native app via:
 *     window.webkit.messageHandlers.apiRequest
 * and proxies authenticated API calls through it (because the file:// origin
 * blocks direct fetch — same constraint under WebView2). On macOS that handler
 * is provided by WebViewController.swift. Here we synthesize the same
 * window.webkit.messageHandlers.* interface, backed by Tauri `invoke`.
 *
 * Must load BEFORE report.js (injected into <head> by sync-frontend.mjs).
 */
(function () {
  const T = window.__TAURI__;
  if (!T || !T.core || !T.core.invoke) {
    console.error("[bridge] window.__TAURI__ not available — is withGlobalTauri enabled?");
    return;
  }
  const invoke = T.core.invoke;
  const opener = T.opener; // open URLs in the system browser

  // postMessage({ id, method, path, body }) -> Rust api_request -> __apiResolve.
  // Mirrors WebViewController.handleApiRequest exactly: resolves with
  // { ok, status, body } where body is the raw response text.
  function apiRequest(msg) {
    invoke("api_request", {
      path: msg.path,
      method: msg.method || "GET",
      body: msg.body != null ? JSON.stringify(msg.body) : null,
    })
      .then((res) => {
        // res = { ok, status, body }
        if (window.__apiResolve) window.__apiResolve(msg.id, res);
      })
      .catch((err) => {
        if (window.__apiResolve)
          window.__apiResolve(msg.id, {
            ok: false,
            status: 0,
            body: JSON.stringify({ error: String(err) }),
          });
      });
  }

  // openSession(slug): fetch the session through the bridge and render it.
  // (On macOS, Swift does this fetch + injectReport; we do the same via the
  // api_request command, then call the frontend's own window.loadReport.)
  function openSession(slug) {
    invoke("api_request", {
      path: "/sessions/" + encodeURIComponent(slug),
      method: "GET",
      body: null,
    })
      .then((res) => {
        if (res.ok && res.body) {
          const data = JSON.parse(res.body);
          if (window.loadReport) window.loadReport(data.data || data);
        }
      })
      .catch((e) => console.error("[bridge] openSession failed", e));
  }

  function openURL(url) {
    if (opener && opener.openUrl) opener.openUrl(url);
    else window.open(url, "_blank");
  }

  function signOut() {
    invoke("sign_out").catch((e) => console.error("[bridge] signOut failed", e));
  }

  // Install the emulated WebKit interface. Each handler exposes postMessage(...)
  // just like WKScriptMessageHandler, so report.js's existing call sites work.
  window.webkit = window.webkit || {};
  window.webkit.messageHandlers = Object.assign(window.webkit.messageHandlers || {}, {
    apiRequest: { postMessage: apiRequest },
    openSession: { postMessage: openSession },
    openURL: { postMessage: openURL },
    signOut: { postMessage: signOut },
  });

  // The Rust host injects sessions / reports / token by calling these globals
  // (defined by report.js): window.loadSessions, window.loadReport, and
  // window._fluentToken. Nothing to do here — they're invoked from Rust via
  // eval once the page is ready.
  console.log("[bridge] Tauri native bridge installed");
})();
