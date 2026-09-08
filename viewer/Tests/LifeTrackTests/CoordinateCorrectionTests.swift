import CoreLocation
import XCTest
@testable import LifeTrack

final class CoordinateCorrectionTests: XCTestCase {
    func testAutomaticCorrectionAppliesMainlandDisplayOffset() {
        let wgs84 = CLLocationCoordinate2D(latitude: 31.2304, longitude: 121.4737)
        let expected = CoordinateCorrection.wgs84ToGCJ02(wgs84)
        let corrected = CoordinateCorrection.displayCoordinate(wgs84, mode: .automatic)

        XCTAssertLessThan(distance(from: expected, to: corrected), 0.1)
        XCTAssertGreaterThan(distance(from: wgs84, to: corrected), 100)
    }

    func testReverseConversionRoundTripsMainlandCoordinate() {
        let wgs84 = CLLocationCoordinate2D(latitude: 31.2304, longitude: 121.4737)
        let gcj02 = CoordinateCorrection.wgs84ToGCJ02(wgs84)
        let roundTrip = CoordinateCorrection.gcj02ToWGS84(gcj02)

        XCTAssertLessThan(distance(from: wgs84, to: roundTrip), 0.1)
    }

    func testAutomaticCorrectionLeavesCoordinateOutsideRegionUnchanged() {
        let coordinate = CLLocationCoordinate2D(latitude: 35.6762, longitude: 139.6503)
        let corrected = CoordinateCorrection.displayCoordinate(coordinate, mode: .automatic)

        XCTAssertEqual(corrected.latitude, coordinate.latitude)
        XCTAssertEqual(corrected.longitude, coordinate.longitude)
    }

    func testOriginalModeNeverChangesCoordinate() {
        let coordinate = CLLocationCoordinate2D(latitude: 31.2304, longitude: 121.4737)
        let displayed = CoordinateCorrection.displayCoordinate(coordinate, mode: .original)

        XCTAssertEqual(displayed.latitude, coordinate.latitude)
        XCTAssertEqual(displayed.longitude, coordinate.longitude)
    }

    private func distance(
        from first: CLLocationCoordinate2D,
        to second: CLLocationCoordinate2D
    ) -> CLLocationDistance {
        CLLocation(latitude: first.latitude, longitude: first.longitude)
            .distance(from: CLLocation(latitude: second.latitude, longitude: second.longitude))
    }
}
