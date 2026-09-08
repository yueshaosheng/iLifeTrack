import XCTest
@testable import LifeTrack

final class LifeTrackNotificationsTests: XCTestCase {
    func testAuthenticationFailureProducesActionableNotification() {
        let message = LifeTrackNotifications.pollMessage(outcome: "auth_required")
        XCTAssertEqual(message?.title, "LifeTrack 需要重新认证")
        XCTAssertTrue(message?.body.contains("打开 LifeTrack") == true)
    }

    func testSuccessDoesNotProduceNotification() {
        XCTAssertNil(LifeTrackNotifications.pollMessage(outcome: "success"))
        XCTAssertNil(LifeTrackNotifications.communicationMessage(outcome: "success"))
    }

    func testCommunicationPermissionFailureProducesNotification() {
        let message = LifeTrackNotifications.communicationMessage(
            outcome: "permission_required"
        )
        XCTAssertTrue(message?.body.contains("完全磁盘访问权限") == true)
    }
}
