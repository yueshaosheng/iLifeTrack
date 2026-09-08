// swift-tools-version: 6.0

import PackageDescription

let package = Package(
    name: "LifeTrack",
    platforms: [.macOS(.v14)],
    products: [
        .executable(name: "LifeTrack", targets: ["LifeTrack"])
    ],
    targets: [
        .executableTarget(
            name: "LifeTrack",
            linkerSettings: [
                .linkedFramework("Security"),
                .linkedLibrary("sqlite3"),
            ]
        ),
        .testTarget(
            name: "LifeTrackTests",
            dependencies: ["LifeTrack"]
        ),
    ]
)
