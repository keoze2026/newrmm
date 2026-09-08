// swift-tools-version:5.7
import PackageDescription

let package = Package(
    name: "RMMCapture",
    platforms: [.macOS(.v12)],
    products: [
        // A dynamic library with C-ABI entry points, loaded from Python.
        .library(name: "RMMCapture", type: .dynamic, targets: ["RMMCapture"]),
    ],
    targets: [
        .target(name: "RMMCapture", path: "Sources/RMMCapture"),
    ]
)
