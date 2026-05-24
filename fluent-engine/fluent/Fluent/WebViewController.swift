import Cocoa
import WebKit

class WebViewController: NSViewController, WKScriptMessageHandler {

    private var webView: WKWebView!
    private var pendingReportJSON: String?

    private let reportsDir: URL = {
        FileManager.default.homeDirectoryForCurrentUser
            .appendingPathComponent(".fluent/reports")
    }()

    override func loadView() {
        let config = WKWebViewConfiguration()
        config.preferences.setValue(true, forKey: "allowFileAccessFromFileURLs")
        // Allow JS on the page to call back into Swift to open a specific session
        config.userContentController.add(self, name: "openSession")

        webView = WKWebView(frame: .zero, configuration: config)
        webView.navigationDelegate = self
        webView.setValue(false, forKey: "drawsBackground")
        view = webView
    }

    override func viewDidLoad() {
        super.viewDidLoad()
        loadHTML()
    }

    // MARK: - HTML loading

    private func loadHTML() {
        // App bundle: Resources/frontend/report.html
        if let url = Bundle.main.url(
            forResource: "report",
            withExtension: "html",
            subdirectory: "frontend"
        ) {
            webView.loadFileURL(url, allowingReadAccessTo: url.deletingLastPathComponent())
            return
        }

        // Dev fallback: frontend/ at repo root (3 levels up from this source file)
        let srcFile = URL(fileURLWithPath: #file)
        let repoRoot = srcFile
            .deletingLastPathComponent()  // Fluent/
            .deletingLastPathComponent()  // fluent/ (inner)
            .deletingLastPathComponent()  // fluent-engine/
            .deletingLastPathComponent()  // repo root
        let devURL = repoRoot.appendingPathComponent("frontend/report.html")

        if FileManager.default.fileExists(atPath: devURL.path) {
            webView.loadFileURL(devURL, allowingReadAccessTo: devURL.deletingLastPathComponent())
        }
    }

    // MARK: - Sessions list (shown on startup)

    private func injectSessions() {
        let sessionsURL = reportsDir.appendingPathComponent("sessions.json")
        guard
            let data = try? Data(contentsOf: sessionsURL),
            let json = String(data: data, encoding: .utf8)
        else {
            // No sessions yet — show onboarding
            return
        }
        let js = "window.loadSessions(\(json));"
        webView.evaluateJavaScript(js) { _, error in
            if let error { print("[Fluent WebView] loadSessions error:", error) }
        }
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
        guard message.name == "openSession", let slug = message.body as? String else { return }
        let sessionURL = reportsDir.appendingPathComponent("\(slug).json")
        guard
            let data = try? Data(contentsOf: sessionURL),
            let json = String(data: data, encoding: .utf8)
        else {
            print("[Fluent] session JSON not found for slug: \(slug)")
            return
        }
        injectReport(json: json)
    }
}

// MARK: - WKNavigationDelegate
extension WebViewController: WKNavigationDelegate {
    func webView(_ webView: WKWebView, didFinish navigation: WKNavigation!) {
        if let json = pendingReportJSON {
            pendingReportJSON = nil
            injectReport(json: json)
        } else {
            injectSessions()
        }
    }
}
