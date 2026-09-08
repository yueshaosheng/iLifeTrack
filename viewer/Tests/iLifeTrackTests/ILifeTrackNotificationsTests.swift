import XCTest
@testable import iLifeTrack

final class ILifeTrackNotificationsTests: XCTestCase {
    func testAuthenticationFailureProducesActionableNotification() {
        let message = ILifeTrackNotifications.pollMessage(outcome: "auth_required")
        XCTAssertEqual(message?.title, "iLifeTrack 需要重新认证")
        XCTAssertTrue(message?.body.contains("打开 iLifeTrack") == true)
    }

    func testSuccessDoesNotProduceNotification() {
        XCTAssertNil(ILifeTrackNotifications.pollMessage(outcome: "success"))
        XCTAssertNil(ILifeTrackNotifications.communicationMessage(outcome: "success"))
    }

    func testCommunicationPermissionFailureProducesNotification() {
        let message = ILifeTrackNotifications.communicationMessage(
            outcome: "permission_required"
        )
        XCTAssertTrue(message?.body.contains("完全磁盘访问权限") == true)
    }
}
