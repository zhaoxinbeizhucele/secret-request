import AppKit
import Foundation
import UserNotifications
import Darwin

struct Notice: Decodable {
    let id: String
    let title: String
    let body: String
    let url: String
    let expires_in_seconds: Double
}

func inputDestination(_ id: String, _ value: String) -> URL? {
    guard id.range(of: "^[A-Za-z0-9_-]{24}$", options: .regularExpression) != nil,
          value.allSatisfy({ character in
              guard let code = character.asciiValue else { return false }
              return code >= 32 && code != 127
          }),
          !value.contains("@"), !value.contains("?"),
          let url = URL(string: value), url.scheme == "https",
          let host = url.host, !host.isEmpty,
          url.user == nil, url.password == nil, url.query == nil,
          let fragment = url.fragment else { return nil }
    let legacy = url.path == "/input/" + id && fragment.range(of: "^[A-Za-z0-9_-]{43}$", options: .regularExpression) != nil
    let shortLink = (url.path == "/i" || url.path == "/" || url.path.isEmpty)
        && fragment.range(of: "^[A-Za-z0-9_-]{22}$", options: .regularExpression) != nil
    return (legacy || shortLink) ? url : nil
}

final class Delegate: NSObject, NSApplicationDelegate, UNUserNotificationCenterDelegate {
    let notice: Notice
    let center = UNUserNotificationCenter.current()
    init(_ notice: Notice) {
        self.notice = notice
        super.init()
    }
    func applicationDidFinishLaunching(_ notification: Notification) {
        center.delegate = self
        center.requestAuthorization(options: [.alert, .sound]) { granted, _ in
            guard granted else { exit(1) }
            let content = UNMutableNotificationContent()
            content.title = self.notice.title
            content.body = self.notice.body
            content.sound = .default
            content.userInfo = ["input_url": self.notice.url]
            self.center.add(UNNotificationRequest(identifier: self.notice.id, content: content, trigger: nil)) { error in
                guard error == nil else { exit(1) }
                FileHandle.standardOutput.write(Data("sent\n".utf8))
                try? FileHandle.standardOutput.close()
            }
        }
        DispatchQueue.main.asyncAfter(deadline: .now() + notice.expires_in_seconds) { NSApp.terminate(nil) }
        signal(SIGTERM, SIG_IGN)
        let termination = DispatchSource.makeSignalSource(signal: SIGTERM, queue: .main)
        termination.setEventHandler { NSApp.terminate(nil) }
        termination.resume()
        signalSource = termination
    }
    var signalSource: DispatchSourceSignal?
    func userNotificationCenter(_ center: UNUserNotificationCenter, willPresent notification: UNNotification,
                                withCompletionHandler completion: @escaping (UNNotificationPresentationOptions) -> Void) {
        completion([.banner, .sound])
    }
    func userNotificationCenter(_ center: UNUserNotificationCenter, didReceive response: UNNotificationResponse,
                                withCompletionHandler completion: @escaping () -> Void) {
        completion()
        DispatchQueue.main.async {
            let id = response.notification.request.identifier
            if response.actionIdentifier == UNNotificationDefaultActionIdentifier,
               let value = response.notification.request.content.userInfo["input_url"] as? String,
               let url = inputDestination(id, value) {
                NSWorkspace.shared.open(url)
            }
            // A shared app identity can route another helper's response here.
            if id == self.notice.id { NSApp.terminate(nil) }
        }
    }
    func applicationWillTerminate(_ notification: Notification) {
        center.removeDeliveredNotifications(withIdentifiers: [notice.id])
        center.removePendingNotificationRequests(withIdentifiers: [notice.id])
    }
}

do {
    let data = FileHandle.standardInput.readDataToEndOfFile()
    guard data.count <= 8192 else { exit(1) }
    let notice = try JSONDecoder().decode(Notice.self, from: data)
    guard inputDestination(notice.id, notice.url) != nil,
          notice.expires_in_seconds > 0, notice.expires_in_seconds <= 1800 else { exit(1) }
    let application = NSApplication.shared
    application.setActivationPolicy(.accessory)
    let delegate = Delegate(notice)
    application.delegate = delegate
    withExtendedLifetime(delegate) { application.run() }
} catch { exit(1) }
