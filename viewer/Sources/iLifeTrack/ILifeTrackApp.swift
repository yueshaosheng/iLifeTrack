import SwiftUI

struct ILifeTrackApp: App {
    init() {
        ILifeTrackNotifications.requestAuthorization()
    }

    var body: some Scene {
        WindowGroup("iLifeTrack") {
            ContentView()
                .frame(minWidth: 920, minHeight: 640)
        }
        .defaultSize(width: 1100, height: 760)
    }
}
