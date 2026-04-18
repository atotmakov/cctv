import pytest
from requests.auth import HTTPDigestAuth

from cctv.config import CameraConfig


@pytest.fixture
def camera_config() -> CameraConfig:
    return CameraConfig(
        subnet="192.168.1.0/24",
        username="root",
        password="testpass",
        smb_ip="192.168.1.10",
        smb_share="/mnt/cctv",
        smb_username="smbuser",
        smb_password="smbpass",
        motion_enabled=True,
        motion_sensitivity=90,
        recording_retention_days=33,
        timeout=5,
    )


@pytest.fixture
def mock_auth() -> HTTPDigestAuth:
    return HTTPDigestAuth("root", "testpass")


@pytest.fixture
def vapix_brand_response() -> str:
    return (
        "root.Brand.Brand=AXIS\n"
        "root.Brand.ProdFullName=AXIS P3245-V\n"
        "root.Brand.ProdNbr=P3245-V\n"
    )


@pytest.fixture
def smb_params_response() -> dict[str, str]:
    """VAPIX SMB params matching the default camera_config fixture — all fields at desired state."""
    from cctv.reconciler import _SMB_HOST, _SMB_SHARE, _SMB_USER, _SMB_PASS
    return {
        _SMB_HOST: "192.168.1.10",   # matches camera_config.smb_ip
        _SMB_SHARE: "/mnt/cctv",     # matches camera_config.smb_share
        _SMB_USER: "smbuser",        # matches camera_config.smb_username
        _SMB_PASS: "smbpass",        # matches camera_config.smb_password
    }


@pytest.fixture
def motion_params_response() -> dict[str, str]:
    """VAPIX motion params: M0 full-frame window, sensitivity matching camera_config (50)."""
    return {
        "root.Motion.M0.Name": "full_frame",
        "root.Motion.M0.Left": "0",
        "root.Motion.M0.Right": "9999",
        "root.Motion.M0.Top": "0",
        "root.Motion.M0.Bottom": "9999",
        "root.Motion.M0.WindowType": "include",
        "root.Motion.M0.Sensitivity": "90",
        "root.Motion.M0.History": "90",
        "root.Motion.M0.ObjectSize": "15",
    }


@pytest.fixture
def storage_params_response() -> dict[str, str]:
    """VAPIX storage params matching the default camera_config fixture — retention at desired state."""
    from cctv.reconciler import _STORAGE_RETENTION
    return {
        _STORAGE_RETENTION: "33",  # matches camera_config.recording_retention_days = 33
    }


@pytest.fixture
def motion_action_config():
    """ActionConfiguration for motion→record-to-NetworkShare (already correctly set up)."""
    from cctv.vapix import ActionConfiguration
    return ActionConfiguration(
        config_id=2,
        name="cctv_motion_record",
        template_token="com.axis.action.unlimited.recording.storage",
        parameters={"storage_id": "NetworkShare", "post_duration": "5000", "pre_duration": "5000", "stream_options": ""},
    )


@pytest.fixture
def time_params_response() -> dict[str, str]:
    """VAPIX time params: timezone UTC0, NTP server 192.168.1.100, static (no DHCP)."""
    return {
        "root.Time.POSIXTimeZone": "UTC0",
        "root.Time.NTP.Server": "192.168.1.100",
        "root.Time.ObtainFromDHCP": "no",
        "root.Time.SyncSource": "NTP",
    }


@pytest.fixture
def volatile_hostname_response() -> dict[str, str]:
    """Default: DHCP has not assigned a hostname — no hostname sync triggered."""
    return {
        "root.Network.VolatileHostName.HostName": "",
        "root.Network.VolatileHostName.ObtainFromDHCP": "yes",
    }


@pytest.fixture
def motion_action_rule(motion_action_config):
    """ActionRule pointing to the motion_action_config (fully configured)."""
    from cctv.vapix import ActionRule
    return ActionRule(
        rule_id=2,
        name="cctv_motion_record",
        enabled=True,
        topic="tns1:VideoAnalytics/tnsaxis:MotionDetection//.",
        primary_action=motion_action_config.config_id,
    )
