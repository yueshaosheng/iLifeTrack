import SwiftUI

struct LifeTrackApp: App {
    init() {
        LifeTrackNotifications.requestAuthorization()
    }

    var body: some Scene {
        WindowGroup("LifeTrack") {
            ContentView()
                .frame(minWidth: 920, minHeight: 640)
        }
        .defaultSize(width: 1100, height: 760)
    }
}
