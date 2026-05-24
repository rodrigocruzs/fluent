import Cocoa

class ReportWindowController: NSWindowController {

    init() {
        let window = NSWindow(
            contentRect: NSRect(x: 0, y: 0, width: 1080, height: 720),
            styleMask: [.titled, .closable, .miniaturizable, .resizable, .fullSizeContentView],
            backing: .buffered,
            defer: false
        )
        window.title = "Fluent"
        window.titlebarAppearsTransparent = false
        window.minSize = NSSize(width: 640, height: 480)
        window.contentViewController = WebViewController()
        super.init(window: window)
        window.center()
    }

    required init?(coder: NSCoder) { fatalError("not used") }

    private var webViewController: WebViewController? {
        window?.contentViewController as? WebViewController
    }

    func loadReportJSON(_ json: String) {
        webViewController?.loadReportJSON(json)
    }
}
