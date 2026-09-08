// swift-tools-version: 6.0

import PackageDescription

let package = Package(
    name: "iLifeTrack",
    platforms: [.macOS(.v14)],
    products: [
        .executable(name: "iLifeTrack", targets: ["iLifeTrack"])
    ],
    targets: [
        .executableTarget(
            name: "iLifeTrack",
            linkerSettings: [
                .linkedFramework("Security"),
                .linkedLibrary("sqlite3"),
            ]
        ),
        .testTarget(
            name: "iLifeTrackTests",
            dependencies: ["iLifeTrack"]
        ),
    ]
)
