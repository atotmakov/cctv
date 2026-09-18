import pytest
from requests.auth import HTTPDigestAuth

from cctv.config import (
    CameraConfig,
    Profile,
    S3StorageConfig,
    SmbStorageConfig,
    StorageConfig,
)


@pytest.fixture
def legacy_profile() -> Profile:
    """AXIS OS 5.x fleet: legacy root.Motion group + SMB network-share recording.

    target_firmware is deliberately None so reconcile() skips the firmware
    precondition read — tests that exercise it set it explicitly.
    """
    return Profile(
        name="legacy-smb",
        models=["P3245-V", "M3005", "P1204", "M2014-E"],
        target_firmware=None,
        applications={},
        motion_detection={
            "enabled": True,
            "sensitivity": 90,
            "pre_trigger_time": 5,
            "post_trigger_time": 5,
        },
        storage=StorageConfig(
            backend="smb",
            smb=SmbStorageConfig(
                ip="192.168.1.10",
                share="/mnt/cctv",
                username="smbuser",
                password="smbpass",
            ),
        ),
    )


@pytest.fixture
def s3_profile() -> Profile:
    """AXIS OS 12.x fleet: built-in VMD4 + SD-card recording synced to S3."""
    return Profile(
        name="m3085v-sd-s3sync",
        models=["M3085-V"],
        target_firmware=None,
        applications={"sd_to_s3_sync": {"app_package_path": "/opt/eap/signed_SD_to_S3_Sync_0_9_5_aarch64.eap"}},
        motion_detection={
            "enabled": True,
            "size_percentage": [5, 5],
            "time_short_lived_limit": 1,
            "distance_swaying_object": 5,
            "pre_trigger_time": 5,
            "post_trigger_time": 2,
        },
        storage=StorageConfig(
            backend="sd_s3sync",
            sd_s3sync=S3StorageConfig(
                endpoint="https://s3.example-provider.com",
                region="us-east-1",
                bucket="my-cctv-bucket",
                access_key="ACCESSKEY",
                secret_key="SECRETKEY",
            ),
        ),
    )


@pytest.fixture
def camera_config(legacy_profile, s3_profile) -> CameraConfig:
    return CameraConfig(
        subnet="192.168.1.0/24",
        username="root",
        password="testpass",
        timeout=5,
        recording_retention_days=33,
        profiles=[legacy_profile, s3_profile],
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
    """VAPIX SMB params matching the legacy_profile fixture — all fields at desired state."""
    from cctv.reconciler import _SMB_HOST, _SMB_SHARE, _SMB_USER, _SMB_PASS
    return {
        _SMB_HOST: "192.168.1.10",   # matches legacy_profile.storage.smb.ip
        _SMB_SHARE: "/mnt/cctv",     # matches legacy_profile.storage.smb.share
        _SMB_USER: "smbuser",        # matches legacy_profile.storage.smb.username
        _SMB_PASS: "smbpass",        # matches legacy_profile.storage.smb.password
    }


@pytest.fixture
def motion_params_response() -> dict[str, str]:
    """VAPIX motion params: M0 full-frame window, sensitivity matching legacy_profile (90)."""
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
    """VAPIX storage params for the smb backend (S1) — retention at desired state."""
    from cctv.reconciler import _STORAGE_RETENTION_S1
    return {
        _STORAGE_RETENTION_S1: "33",  # matches camera_config.recording_retention_days = 33
    }


@pytest.fixture
def sd_storage_params_response() -> dict[str, str]:
    """VAPIX storage params for the sd_s3sync backend (S0) — retention at desired state."""
    from cctv.reconciler import _STORAGE_RETENTION_S0
    return {
        _STORAGE_RETENTION_S0: "33",
    }


@pytest.fixture
def sds3sync_params_response(s3_profile) -> dict[str, str]:
    """root.Sds3sync params already matching the s3_profile fixture — no config write needed."""
    from cctv.reconciler import (
        _SDS3SYNC_HEARTBEAT_INTERVAL_SECONDS,
        _SDS3SYNC_INTERVAL_SECONDS,
        _SDS3SYNC_RECORDING_PATH,
        _SDS3SYNC_S3_INSECURE_TLS,
        _SDS3SYNC_S3_PATH_STYLE,
    )
    s3 = s3_profile.storage.sd_s3sync
    return {
        "root.Sds3sync.S3Endpoint": s3.endpoint,
        "root.Sds3sync.S3Region": s3.region,
        "root.Sds3sync.S3Bucket": s3.bucket,
        "root.Sds3sync.S3AccessKey": s3.access_key,
        "root.Sds3sync.S3SecretKey": s3.secret_key,
        "root.Sds3sync.S3PathStyle": _SDS3SYNC_S3_PATH_STYLE,
        "root.Sds3sync.S3InsecureTLS": _SDS3SYNC_S3_INSECURE_TLS,
        "root.Sds3sync.RecordingPath": _SDS3SYNC_RECORDING_PATH,
        "root.Sds3sync.IntervalSeconds": _SDS3SYNC_INTERVAL_SECONDS,
        "root.Sds3sync.HeartbeatIntervalSeconds": _SDS3SYNC_HEARTBEAT_INTERVAL_SECONDS,
    }


@pytest.fixture
def sds3sync_app_running():
    """InstalledApplication: the sd_to_s3_sync ACAP installed and running."""
    from cctv.vapix import InstalledApplication
    return InstalledApplication(name="sds3sync", nice_name="SD to S3 Sync", status="Running", version="0.9.5")


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
def sd_action_config():
    """ActionConfiguration for motion→record-to-SD_DISK, matching the s3_profile durations."""
    from cctv.vapix import ActionConfiguration
    return ActionConfiguration(
        config_id=4,
        name="cctv_motion_sd_record",
        template_token="com.axis.action.unlimited.recording.storage",
        parameters={"storage_id": "SD_DISK", "pre_duration": "5000", "post_duration": "2000", "stream_options": ""},
    )


@pytest.fixture
def sd_action_rule(sd_action_config):
    """ActionRule on the VMD4 profile topic, pointing at sd_action_config."""
    from cctv.vapix import ActionRule
    return ActionRule(
        rule_id=4,
        name="cctv_motion_sd_record",
        enabled=True,
        topic="tnsaxis:CameraApplicationPlatform/VMD/Camera1Profile1",
        primary_action=sd_action_config.config_id,
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
def vmd_app_running():
    """InstalledApplication: vmd already installed and running (default/healthy state)."""
    from cctv.vapix import InstalledApplication
    return InstalledApplication(name="vmd", nice_name="AXIS Video Motion Detection", status="Running", version="4.3-1")


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
