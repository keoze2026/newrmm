//
//  Native macOS screen capture for the endpoint agent.
//
//  Specification section 5: "Screen capture | ... | ScreenCaptureKit".
//  Section 6: "macOS in Swift/Obj-C with ScreenCaptureKit".
//
//  Why ScreenCaptureKit rather than a plain screen grab: the privacy blank puts
//  a black window over the guest's display with `NSWindowSharingNone`, and
//  ScreenCaptureKit honours that - it keeps delivering frames of the desktop
//  behind the blank, so the operator keeps a live view while the guest sees
//  black. The deprecated CGDisplayCreateImage path does not.
//
//  Exported with the C ABI so the agent can load it with ctypes and present it
//  as an ordinary Python module (see rmm_capture_macos.py).
//
//  Requires macOS 12.3 or newer, which is at or above the specification's
//  floor of macOS 12.
//

import AVFoundation
import CoreMedia
import CoreVideo
import Foundation
import ScreenCaptureKit

/// Holds the most recent frame, shared between the capture queue and callers.
private final class FrameStore: @unchecked Sendable {
    private let lock = NSLock()
    private var pixels: [UInt8] = []
    private var width: Int = 0
    private var height: Int = 0
    private var seen: UInt64 = 0

    func store(_ data: [UInt8], width: Int, height: Int) {
        lock.lock()
        defer { lock.unlock() }
        self.pixels = data
        self.width = width
        self.height = height
        self.seen &+= 1
    }

    func latest() -> (pixels: [UInt8], width: Int, height: Int, seen: UInt64) {
        lock.lock()
        defer { lock.unlock() }
        return (pixels, width, height, seen)
    }
}

@available(macOS 12.3, *)
private final class StreamOutput: NSObject, SCStreamOutput, SCStreamDelegate {
    let store: FrameStore

    init(store: FrameStore) {
        self.store = store
    }

    func stream(_ stream: SCStream,
                didOutputSampleBuffer sampleBuffer: CMSampleBuffer,
                of type: SCStreamOutputType) {
        guard type == .screen,
              CMSampleBufferIsValid(sampleBuffer),
              let imageBuffer = CMSampleBufferGetImageBuffer(sampleBuffer) else {
            return
        }

        CVPixelBufferLockBaseAddress(imageBuffer, .readOnly)
        defer { CVPixelBufferUnlockBaseAddress(imageBuffer, .readOnly) }

        guard let base = CVPixelBufferGetBaseAddress(imageBuffer) else { return }
        let width = CVPixelBufferGetWidth(imageBuffer)
        let height = CVPixelBufferGetHeight(imageBuffer)
        // Rows are padded to the surface stride, so walk row by row rather than
        // assuming width * 4.
        let stride = CVPixelBufferGetBytesPerRow(imageBuffer)
        let source = base.assumingMemoryBound(to: UInt8.self)

        var rgb = [UInt8](repeating: 0, count: width * height * 3)
        for y in 0..<height {
            let row = source + y * stride
            var out = y * width * 3
            for x in 0..<width {
                let pixel = row + x * 4
                // The surface is BGRA; the agent wants packed RGB.
                rgb[out] = pixel[2]
                rgb[out + 1] = pixel[1]
                rgb[out + 2] = pixel[0]
                out += 3
            }
        }
        store.store(rgb, width: width, height: height)
    }

    func stream(_ stream: SCStream, didStopWithError error: Error) {
        NSLog("RMMCapture: the stream stopped: \(error.localizedDescription)")
    }
}

@available(macOS 12.3, *)
private final class CaptureEngine {
    static let shared = CaptureEngine()

    private let store = FrameStore()
    private var stream: SCStream?
    private var output: StreamOutput?
    private var displays: [SCDisplay] = []
    private var currentIndex: Int = -1
    private let queue = DispatchQueue(label: "com.rmm.agent.capture")

    /// Blocking wrapper around ScreenCaptureKit's async content query.
    func refreshDisplays() -> Bool {
        let semaphore = DispatchSemaphore(value: 0)
        var found: [SCDisplay] = []

        SCShareableContent.getExcludingDesktopWindows(false,
                                                      onScreenWindowsOnly: true) { content, error in
            if let error = error {
                NSLog("RMMCapture: could not list displays: \(error.localizedDescription)")
            }
            found = content?.displays ?? []
            semaphore.signal()
        }

        // A refusal here almost always means Screen Recording permission has not
        // been granted; the caller reports that rather than hanging.
        if semaphore.wait(timeout: .now() + 10) == .timedOut {
            return false
        }
        displays = found
        return !displays.isEmpty
    }

    func displayCount() -> Int {
        if displays.isEmpty { _ = refreshDisplays() }
        return displays.count
    }

    func displayInfo(_ index: Int) -> (Int, Int, Int, Int, Int)? {
        if displays.isEmpty { _ = refreshDisplays() }
        guard index >= 0, index < displays.count else { return nil }
        let display = displays[index]
        return (Int(display.displayID),
                display.width,
                display.height,
                Int(display.frame.origin.x),
                Int(display.frame.origin.y))
    }

    func start(index: Int) -> Bool {
        if displays.isEmpty, !refreshDisplays() { return false }
        guard index >= 0, index < displays.count else { return false }
        if stream != nil, currentIndex == index { return true }

        stop()

        let display = displays[index]
        let configuration = SCStreamConfiguration()
        configuration.width = display.width
        configuration.height = display.height
        configuration.pixelFormat = kCVPixelFormatType_32BGRA
        configuration.showsCursor = true
        configuration.queueDepth = 3
        // 30 fps ceiling; the agent's own rate controller throttles below this.
        configuration.minimumFrameInterval = CMTime(value: 1, timescale: 30)

        let filter = SCContentFilter(display: display, excludingWindows: [])
        let handler = StreamOutput(store: store)
        let newStream = SCStream(filter: filter, configuration: configuration, delegate: handler)

        do {
            try newStream.addStreamOutput(handler, type: .screen, sampleHandlerQueue: queue)
        } catch {
            NSLog("RMMCapture: could not add the stream output: \(error.localizedDescription)")
            return false
        }

        let semaphore = DispatchSemaphore(value: 0)
        var started = false
        newStream.startCapture { error in
            if let error = error {
                NSLog("RMMCapture: could not start capture: \(error.localizedDescription)")
            } else {
                started = true
            }
            semaphore.signal()
        }
        if semaphore.wait(timeout: .now() + 10) == .timedOut || !started {
            return false
        }

        stream = newStream
        output = handler
        currentIndex = index

        // Wait briefly for the first frame so the caller's first grab succeeds.
        for _ in 0..<50 {
            if store.latest().seen > 0 { break }
            Thread.sleep(forTimeInterval: 0.02)
        }
        return true
    }

    func stop() {
        if let stream = stream {
            let semaphore = DispatchSemaphore(value: 0)
            stream.stopCapture { _ in semaphore.signal() }
            _ = semaphore.wait(timeout: .now() + 5)
        }
        stream = nil
        output = nil
        currentIndex = -1
    }

    func copyLatest(into buffer: UnsafeMutablePointer<UInt8>, capacity: Int) -> (Int, Int) {
        let frame = store.latest()
        guard frame.seen > 0, !frame.pixels.isEmpty else { return (0, 0) }
        let needed = frame.width * frame.height * 3
        guard needed <= capacity else { return (-1, -1) }
        frame.pixels.withUnsafeBufferPointer { source in
            buffer.update(from: source.baseAddress!, count: needed)
        }
        return (frame.width, frame.height)
    }

    func latestSize() -> (Int, Int) {
        let frame = store.latest()
        return (frame.width, frame.height)
    }
}

// MARK: - C ABI, loaded from Python with ctypes

@_cdecl("rmm_capture_open")
public func rmm_capture_open(_ index: Int32) -> Int32 {
    guard #available(macOS 12.3, *) else { return -2 }
    return CaptureEngine.shared.start(index: Int(index)) ? 0 : -1
}

@_cdecl("rmm_capture_close")
public func rmm_capture_close() {
    guard #available(macOS 12.3, *) else { return }
    CaptureEngine.shared.stop()
}

@_cdecl("rmm_capture_display_count")
public func rmm_capture_display_count() -> Int32 {
    guard #available(macOS 12.3, *) else { return 0 }
    return Int32(CaptureEngine.shared.displayCount())
}

/// Fills `out` with (displayID, width, height, left, top). Returns 0 on success.
@_cdecl("rmm_capture_display_info")
public func rmm_capture_display_info(_ index: Int32,
                                     _ out: UnsafeMutablePointer<Int32>) -> Int32 {
    guard #available(macOS 12.3, *) else { return -2 }
    guard let info = CaptureEngine.shared.displayInfo(Int(index)) else { return -1 }
    out[0] = Int32(info.0)
    out[1] = Int32(info.1)
    out[2] = Int32(info.2)
    out[3] = Int32(info.3)
    out[4] = Int32(info.4)
    return 0
}

/// Size of the most recent frame, so the caller can size its buffer.
@_cdecl("rmm_capture_frame_size")
public func rmm_capture_frame_size(_ out: UnsafeMutablePointer<Int32>) -> Int32 {
    guard #available(macOS 12.3, *) else { return -2 }
    let (width, height) = CaptureEngine.shared.latestSize()
    out[0] = Int32(width)
    out[1] = Int32(height)
    return width > 0 ? 0 : -1
}

/// Copies the most recent frame as packed RGB. Returns bytes written, or < 0.
@_cdecl("rmm_capture_grab")
public func rmm_capture_grab(_ buffer: UnsafeMutablePointer<UInt8>,
                             _ capacity: Int32) -> Int32 {
    guard #available(macOS 12.3, *) else { return -2 }
    let (width, height) = CaptureEngine.shared.copyLatest(into: buffer,
                                                          capacity: Int(capacity))
    if width <= 0 { return -1 }
    return Int32(width * height * 3)
}
