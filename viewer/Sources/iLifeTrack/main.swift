import Foundation

if CommandLine.arguments.contains("--background-service") {
    guard let resources = Bundle.main.resourceURL else {
        fputs("iLifeTrack resources are unavailable.\n", stderr)
        exit(2)
    }
    let backend = resources.appendingPathComponent("backend/ilifetrack/ilifetrack")
    guard FileManager.default.isExecutableFile(atPath: backend.path) else {
        fputs("iLifeTrack background component is unavailable.\n", stderr)
        exit(2)
    }

    exit(BackgroundServiceRunner().run(backend: backend))
} else {
    ILifeTrackApp.main()
}
