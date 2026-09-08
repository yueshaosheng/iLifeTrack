import Foundation
import MapKit

enum CoordinateCorrectionMode: String, CaseIterable, Identifiable {
    case automatic
    case original

    var id: String { rawValue }

    var title: String {
        switch self {
        case .automatic: "中国大陆自动校正"
        case .original: "原始坐标"
        }
    }
}

enum CoordinateCorrection {
    static func displayCoordinate(
        _ coordinate: CLLocationCoordinate2D,
        mode: CoordinateCorrectionMode
    ) -> CLLocationCoordinate2D {
        switch mode {
        case .automatic:
            wgs84ToGCJ02(coordinate)
        case .original:
            coordinate
        }
    }

    // iLifeTrack stores the Find My web endpoint's original coordinates. For
    // the Apple map served in mainland China, apply the GCJ-02 display offset
    // without changing the database values.
    static func gcj02ToWGS84(_ coordinate: CLLocationCoordinate2D) -> CLLocationCoordinate2D {
        guard isInsideChinaOffsetRegion(coordinate) else { return coordinate }

        var minimumLatitude = coordinate.latitude - 0.01
        var maximumLatitude = coordinate.latitude + 0.01
        var minimumLongitude = coordinate.longitude - 0.01
        var maximumLongitude = coordinate.longitude + 0.01
        var candidate = coordinate

        // Solve WGS84 -> GCJ02 in reverse. The iteration leaves sub-meter
        // residual error and is more reliable than a single-pass approximation.
        for _ in 0 ..< 30 {
            candidate = CLLocationCoordinate2D(
                latitude: (minimumLatitude + maximumLatitude) / 2,
                longitude: (minimumLongitude + maximumLongitude) / 2
            )
            let projected = wgs84ToGCJ02(candidate)
            let latitudeError = projected.latitude - coordinate.latitude
            let longitudeError = projected.longitude - coordinate.longitude

            if abs(latitudeError) < 1e-7, abs(longitudeError) < 1e-7 {
                break
            }
            if latitudeError > 0 {
                maximumLatitude = candidate.latitude
            } else {
                minimumLatitude = candidate.latitude
            }
            if longitudeError > 0 {
                maximumLongitude = candidate.longitude
            } else {
                minimumLongitude = candidate.longitude
            }
        }
        return candidate
    }

    static func wgs84ToGCJ02(_ coordinate: CLLocationCoordinate2D) -> CLLocationCoordinate2D {
        guard isInsideChinaOffsetRegion(coordinate) else { return coordinate }

        let semiMajorAxis = 6_378_245.0
        let eccentricitySquared = 0.006_693_421_622_965_943
        let x = coordinate.longitude - 105.0
        let y = coordinate.latitude - 35.0
        var latitudeDelta = transformLatitude(x: x, y: y)
        var longitudeDelta = transformLongitude(x: x, y: y)
        let latitudeRadians = coordinate.latitude / 180.0 * .pi
        var magic = sin(latitudeRadians)
        magic = 1 - eccentricitySquared * magic * magic
        let squareRootMagic = sqrt(magic)
        latitudeDelta = latitudeDelta * 180.0
            / ((semiMajorAxis * (1 - eccentricitySquared)) / (magic * squareRootMagic) * .pi)
        longitudeDelta = longitudeDelta * 180.0
            / (semiMajorAxis / squareRootMagic * cos(latitudeRadians) * .pi)
        return CLLocationCoordinate2D(
            latitude: coordinate.latitude + latitudeDelta,
            longitude: coordinate.longitude + longitudeDelta
        )
    }

    static func isInsideChinaOffsetRegion(_ coordinate: CLLocationCoordinate2D) -> Bool {
        coordinate.longitude >= 72.004
            && coordinate.longitude <= 137.8347
            && coordinate.latitude >= 0.8293
            && coordinate.latitude <= 55.8271
    }

    private static func transformLatitude(x: Double, y: Double) -> Double {
        var value = -100.0 + 2.0 * x + 3.0 * y + 0.2 * y * y
            + 0.1 * x * y + 0.2 * sqrt(abs(x))
        value += (20.0 * sin(6.0 * x * .pi) + 20.0 * sin(2.0 * x * .pi)) * 2.0 / 3.0
        value += (20.0 * sin(y * .pi) + 40.0 * sin(y / 3.0 * .pi)) * 2.0 / 3.0
        value += (160.0 * sin(y / 12.0 * .pi) + 320 * sin(y * .pi / 30.0)) * 2.0 / 3.0
        return value
    }

    private static func transformLongitude(x: Double, y: Double) -> Double {
        var value = 300.0 + x + 2.0 * y + 0.1 * x * x
            + 0.1 * x * y + 0.1 * sqrt(abs(x))
        value += (20.0 * sin(6.0 * x * .pi) + 20.0 * sin(2.0 * x * .pi)) * 2.0 / 3.0
        value += (20.0 * sin(x * .pi) + 40.0 * sin(x / 3.0 * .pi)) * 2.0 / 3.0
        value += (150.0 * sin(x / 12.0 * .pi) + 300.0 * sin(x / 30.0 * .pi)) * 2.0 / 3.0
        return value
    }
}
