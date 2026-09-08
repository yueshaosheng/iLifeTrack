import Foundation

if CommandLine.arguments.contains("--background-service") {
    guard let resources = Bundle.main.resourceURL else {
        fputs("LifeTrack resources are unavailable.\n", stderr)
        exit(2)
    }
    let backend = resources.appendingPathComponent("backend/lifetrack/lifetrack")
    guard FileManager.default.isExecutableFile(atPath: backend.path) else {
        fputs("LifeTrack background component is unavailable.\n", stderr)
        exit(2)
    }

    exit(BackgroundServiceRunner().run(backend: backend))
} else {
    LifeTrackApp.main()
}
