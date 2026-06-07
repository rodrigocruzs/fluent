import Cocoa
import WebKit
import Security

class WebViewController: NSViewController, WKScriptMessageHandler {

    private var webView: WKWebView!
    private var pendingReportJSON: String?
    private var pendingShowSettings = false
    private var authPollTimer: Timer?
    private var cachedToken: String?

    private let pendingAuthURL: URL = {
        FileManager.default.homeDirectoryForCurrentUser
            .appendingPathComponent(".fluent/pending_auth.json")
    }()

    private let reportsDir: URL = {
        FileManager.default.homeDirectoryForCurrentUser
            .appendingPathComponent(".fluent/reports")
    }()

    override func loadView() {
        let config = WKWebViewConfiguration()
        config.preferences.setValue(true, forKey: "allowFileAccessFromFileURLs")
        // Allow JS on the page to call back into Swift to open a specific session
        config.userContentController.add(self, name: "openSession")
        config.userContentController.add(self, name: "authComplete")
        config.userContentController.add(self, name: "signOut")
        config.userContentController.add(self, name: "openURL")

        webView = WKWebView(frame: .zero, configuration: config)
        webView.navigationDelegate = self
        if #available(macOS 13.3, *) {
            webView.isInspectable = true
        }
        view = webView
    }

    override func viewDidLoad() {
        super.viewDidLoad()
        loadHTML()
    }

    // MARK: - HTML loading

    private func loadHTML() {
        if let url = Bundle.main.url(forResource: "report", withExtension: "html") {
            print("[Fluent] loading from bundle: \(url.path)")
            webView.loadFileURL(url, allowingReadAccessTo: url.deletingLastPathComponent())
            return
        }

        // Try to locate frontend/ by walking up from the .app bundle or exe path.
        // Handles both: repo build/ layout and Xcode DerivedData layout.
        // Walk up from the .app bundle to find frontend/report.html in a dev layout
        let candidates: [URL] = {
            var urls: [URL] = []
            var dir = Bundle.main.bundleURL
            for _ in 0..<10 {
                dir = dir.deletingLastPathComponent()
                urls.append(dir.appendingPathComponent("frontend/report.html"))
            }
            return urls
        }()
        guard let devURL = candidates.first(where: { FileManager.default.fileExists(atPath: $0.path) }) else {
            print("[Fluent] report.html not found in bundle or dev layout")
            webView.loadHTMLString("<html><body style='font-family:system-ui;padding:40px'><h1>Fluent</h1><p style='color:#888'>report.html not found.</p></body></html>", baseURL: nil)
            return
        }

        print("[Fluent] loading dev path: \(devURL.path)")
        webView.loadFileURL(devURL, allowingReadAccessTo: devURL.deletingLastPathComponent())
    }

    // MARK: - Sessions list (shown on startup)

    private func getToken() -> String? {
        if let cached = cachedToken { return cached }
        let query: [String: Any] = [
            kSecClass as String: kSecClassGenericPassword,
            kSecAttrService as String: "fluent",
            kSecAttrAccount as String: "jwt_token",
            kSecReturnData as String: true,
            kSecMatchLimit as String: kSecMatchLimitOne,
        ]
        var result: AnyObject?
        guard SecItemCopyMatching(query as CFDictionary, &result) == errSecSuccess,
              let data = result as? Data,
              let token = String(data: data, encoding: .utf8)
        else { return nil }
        cachedToken = token
        return token
    }

    private func injectSessions() {
        // First try the keychain token (set by the Python engine after sign-in)
        // Fall back to localStorage token (set by the JS frontend)
        // If neither exists, show the sign-in screen
        let keychainToken = getToken()

        if keychainToken == nil {
            // Check if the JS frontend has a token in localStorage
            webView.evaluateJavaScript("localStorage.getItem('fluent_token')") { [weak self] result, _ in
                if let token = result as? String, !token.isEmpty {
                    self?.fetchAndInjectSessions(token: token)
                } else {
                    self?.webView.evaluateJavaScript("window.showOnboarding && window.showOnboarding();")
                }
            }
            return
        }

        fetchAndInjectSessions(token: keychainToken!)
    }

    private func fetchAndInjectSessions(token: String) {
        let group = DispatchGroup()
        var sessions: [[String: Any]] = []
        var upNext: [[String: Any]] = []

        // Fetch sessions list
        group.enter()
        var sessionsReq = URLRequest(url: URL(string: "https://www.tryfluent.co/api/sessions")!)
        sessionsReq.setValue("Bearer \(token)", forHTTPHeaderField: "Authorization")
        URLSession.shared.dataTask(with: sessionsReq) { data, response, _ in
            defer { group.leave() }
            guard let data,
                  (response as? HTTPURLResponse)?.statusCode == 200,
                  let parsed = try? JSONSerialization.jsonObject(with: data) as? [[String: Any]]
            else { return }
            sessions = parsed
        }.resume()

        // Fetch calendar events
        group.enter()
        var calReq = URLRequest(url: URL(string: "https://www.tryfluent.co/api/calendar/upcoming")!)
        calReq.setValue("Bearer \(token)", forHTTPHeaderField: "Authorization")
        URLSession.shared.dataTask(with: calReq) { data, response, _ in
            defer { group.leave() }
            let status = (response as? HTTPURLResponse)?.statusCode ?? -1
            print("[Fluent] calendar status:", status, String(data: data ?? Data(), encoding: .utf8) ?? "")
            guard let data, status == 200,
                  let parsed = try? JSONSerialization.jsonObject(with: data) as? [[String: Any]]
            else { return }
            upNext = parsed
        }.resume()

        group.notify(queue: .main) { [weak self] in
            guard let self,
                  let sessionsJSON = try? JSONSerialization.data(withJSONObject: sessions),
                  let sessionsStr  = String(data: sessionsJSON, encoding: .utf8),
                  let upNextJSON   = try? JSONSerialization.data(withJSONObject: upNext),
                  let upNextStr    = String(data: upNextJSON, encoding: .utf8)
            else { return }
            let safeToken = token.replacingOccurrences(of: "\\", with: "\\\\").replacingOccurrences(of: "'", with: "\\'")
            let js = "localStorage.setItem('fluent_token', '\(safeToken)'); window.loadSessions(\(sessionsStr), \(upNextStr));"
            self.webView.evaluateJavaScript(js) { _, error in
                if let error { print("[Fluent WebView] loadSessions error:", error) }
            }
        }
    }

    private func showSettingsIfPending() {
        guard pendingShowSettings else { return }
        pendingShowSettings = false
        webView.evaluateJavaScript("window.showSettings && window.showSettings();")
    }

    private func saveTokenToEngine(_ token: String) {
        guard let url = URL(string: "http://127.0.0.1:2788/signin"),
              let body = try? JSONSerialization.data(withJSONObject: ["token": token]) else { return }
        var req = URLRequest(url: url)
        req.httpMethod = "POST"
        req.setValue("application/json", forHTTPHeaderField: "Content-Type")
        req.httpBody = body
        URLSession.shared.dataTask(with: req) { _, _, error in
            if let error { print("[Fluent] saveTokenToEngine error:", error) }
        }.resume()
    }

    func showOnboarding() {
        webView.evaluateJavaScript("window.showOnboarding && window.showOnboarding();")
        startAuthPolling()
    }

    private func startAuthPolling() {
        authPollTimer?.invalidate()
        authPollTimer = Timer.scheduledTimer(withTimeInterval: 1.0, repeats: true) { [weak self] _ in
            self?.checkPendingAuth()
        }
    }

    private func stopAuthPolling() {
        authPollTimer?.invalidate()
        authPollTimer = nil
    }

    private func checkPendingAuth() {
        guard let data = try? Data(contentsOf: pendingAuthURL),
              let obj  = try? JSONSerialization.jsonObject(with: data) as? [String: String],
              let token = obj["token"], !token.isEmpty
        else { return }
        // Consume the file immediately so we don't process it twice
        try? FileManager.default.removeItem(at: pendingAuthURL)
        stopAuthPolling()
        let name  = obj["name"]  ?? ""
        let email = obj["email"] ?? ""
        handleGoogleAuthCallback(token: token, name: name, email: email)
    }

    func clearTokenAndShowOnboarding() {
        cachedToken = nil
        webView.evaluateJavaScript("localStorage.removeItem('fluent_token'); window.showOnboarding && window.showOnboarding();")
    }

    func showSettings() {
        guard !webView.isLoading, webView.url != nil else {
            pendingShowSettings = true
            return
        }
        webView.evaluateJavaScript("window.showSettings && window.showSettings();")
    }

    func syncBillingStatus() {
        webView.evaluateJavaScript("window.syncBillingStatus && window.syncBillingStatus();")
    }

    func handleGoogleAuthCallback(token: String, name: String, email: String) {
        stopAuthPolling()
        let safeToken = token.replacingOccurrences(of: "\\", with: "\\\\").replacingOccurrences(of: "'", with: "\\'")
        let js = """
        localStorage.setItem('fluent_token', '\(safeToken)');
        if (window.webkit && window.webkit.messageHandlers && window.webkit.messageHandlers.authComplete) {
          window.webkit.messageHandlers.authComplete.postMessage('\(safeToken)');
        }
        """
        webView.evaluateJavaScript(js) { [weak self] _, _ in
            self?.saveTokenToEngine(token)
            self?.injectSessions()
        }
    }

    func showGoogleAuthError(_ message: String) {
        let safe = message.replacingOccurrences(of: "\\", with: "\\\\").replacingOccurrences(of: "'", with: "\\'")
        webView.evaluateJavaScript("""
        window.showOnboarding && window.showOnboarding();
        var el = document.getElementById('auth-error');
        if (el) el.textContent = 'Google sign-in failed: \(safe)';
        """)
    }

    // MARK: - Report injection (latest or specific)

    func loadReportJSON(_ json: String) {
        guard !webView.isLoading, webView.url != nil else {
            pendingReportJSON = json
            return
        }
        injectReport(json: json)
    }

    private func injectReport(json: String) {
        let js = "window.loadReport(\(json));"
        webView.evaluateJavaScript(js) { _, error in
            if let error { print("[Fluent WebView] loadReport error:", error) }
        }
    }

    // MARK: - WKScriptMessageHandler (JS → Swift: open a specific session)

    func userContentController(_ userContentController: WKUserContentController, didReceive message: WKScriptMessage) {
        if message.name == "authComplete" {
            if let token = message.body as? String, !token.isEmpty {
                saveTokenToEngine(token)
            }
            injectSessions()
            return
        }
        if message.name == "signOut" {
            var req = URLRequest(url: URL(string: "http://127.0.0.1:2788/signout")!)
            req.httpMethod = "POST"
            URLSession.shared.dataTask(with: req) { _, _, _ in }.resume()
            DispatchQueue.main.async { self.clearTokenAndShowOnboarding() }
            return
        }
        if message.name == "openURL", let urlString = message.body as? String,
           let url = URL(string: urlString) {
            NSWorkspace.shared.open(url)
            return
        }
        guard message.name == "openSession", let slug = message.body as? String else { return }
        let encoded = slug.addingPercentEncoding(withAllowedCharacters: .urlPathAllowed) ?? slug
        // Read token from localStorage (already injected on startup) to avoid keychain access
        webView.evaluateJavaScript("localStorage.getItem('fluent_token')") { [weak self] result, _ in
            guard let self, let token = result as? String, !token.isEmpty else {
                print("[Fluent] openSession: no token in localStorage")
                return
            }
            var req = URLRequest(url: URL(string: "https://www.tryfluent.co/api/sessions/\(encoded)")!)
            req.setValue("Bearer \(token)", forHTTPHeaderField: "Authorization")
            URLSession.shared.dataTask(with: req) { [weak self] data, response, _ in
                DispatchQueue.main.async {
                    guard let self,
                          let data = data,
                          let json = String(data: data, encoding: .utf8),
                          (response as? HTTPURLResponse)?.statusCode == 200
                    else {
                        print("[Fluent] openSession: failed to fetch slug \(slug)")
                        return
                    }
                    self.injectReport(json: json)
                }
            }.resume()
        }
    }
}

// MARK: - WKNavigationDelegate
extension WebViewController: WKNavigationDelegate {
    func webView(_ webView: WKWebView, didFinish navigation: WKNavigation!) {
        print("[Fluent] webView didFinish: \(webView.url?.absoluteString ?? "nil")")
        if pendingShowSettings {
            pendingShowSettings = false
            webView.evaluateJavaScript("window.showSettings && window.showSettings();")
        } else if let json = pendingReportJSON {
            pendingReportJSON = nil
            injectReport(json: json)
        } else {
            injectSessions()
        }
        // Start polling for Google OAuth callback in case user is on onboarding
        startAuthPolling()
    }

    func webView(_ webView: WKWebView, didFail navigation: WKNavigation!, withError error: Error) {
        print("[Fluent] webView didFail: \(error)")
    }

    func webView(_ webView: WKWebView, didFailProvisionalNavigation navigation: WKNavigation!, withError error: Error) {
        print("[Fluent] webView didFailProvisional: \(error)")
    }
}
