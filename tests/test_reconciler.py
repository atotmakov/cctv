from __future__ import annotations

import pytest
from unittest.mock import patch, call

from cctv.reconciler import (
    reconcile,
    CameraResult,
    CameraStatus,
    _SMB_HOST,
    _SMB_SHARE,
    _SMB_USER,
    _SMB_PASS,
    _STORAGE_RETENTION_S0,
    _STORAGE_RETENTION_S1,
    _FIRMWARE_VERSION,
    _TIME_TIMEZONE,
    _NETWORK_HOSTNAME,
    _NETWORK_VOLATILE_HOSTNAME,
    find_network_share_index,
    smb_param_keys,
)
from cctv.scanner import DiscoveredCamera
from cctv.vapix import VapixError

CAM = DiscoveredCamera(ip="192.168.1.101", model="AXIS P3245-V")
SD_CAM = DiscoveredCamera(ip="192.168.0.24", model="AXIS M3085-V")

# Sensitivity key of the full-frame window in the motion_params_response fixture.
# The reconciler derives this per-camera via full_frame_sensitivity_key() rather
# than hardcoding a window index, so it is a test-side constant, not a source one.
_MOTION_SENSITIVITY = "root.Motion.M0.Sensitivity"


@pytest.fixture(autouse=True)
def default_soap_mocks(motion_action_config, motion_action_rule):
    """Default: camera already has a motion rule. Tests that exercise SOAP creation override these.

    remove_action_rule/remove_action_configuration are mocked here too (not just
    add_*) because a legacy-app camera (use_legacy_app_topic=True) now correctly
    treats the default built-in-topic motion_action_rule as a migration target —
    tests that aren't specifically exercising action-rule content but happen to
    combine with a legacy-app fixture would otherwise hit these unmocked and
    attempt a real network call.
    """
    with patch("cctv.reconciler.vapix.get_action_configurations", return_value=[motion_action_config]), \
         patch("cctv.reconciler.vapix.get_action_rules", return_value=[motion_action_rule]), \
         patch("cctv.reconciler.vapix.add_action_configuration"), \
         patch("cctv.reconciler.vapix.add_action_rule"), \
         patch("cctv.reconciler.vapix.remove_action_rule"), \
         patch("cctv.reconciler.vapix.remove_action_configuration"):
        yield


@pytest.fixture(autouse=True)
def default_vmd_app_mocks(vmd_app_running):
    """Default: vmd app already installed and running. Tests exercising install/start override this."""
    with patch("cctv.reconciler.vapix.get_applications", return_value=[vmd_app_running]), \
         patch("cctv.reconciler.vapix.upload_application") as mock_upload, \
         patch("cctv.reconciler.vapix.start_application") as mock_start:
        yield mock_upload, mock_start


@pytest.fixture(autouse=True)
def default_vmd_area_mocks():
    """Default: legacy app's own detection area already full-frame (no-op for
    _ensure_vmd_app_area). Tests exercising the area-expansion path override this."""
    from cctv.vapix import VmdAppArea
    full_frame_area = [VmdAppArea(name="Detection Area", points=[(1.0, 1.0), (1.0, -1.0), (-1.0, -1.0), (-1.0, 1.0)])]
    with patch("cctv.reconciler.vapix.get_vmd_app_config", return_value=full_frame_area) as mock_get_area, \
         patch("cctv.reconciler.vapix.set_vmd_app_config") as mock_set_area:
        yield mock_get_area, mock_set_area


@pytest.fixture(autouse=True)
def default_vmd4_area_mocks():
    """Default: built-in VMD3/VMD4 app's own profile area already full-frame
    (no-op for _ensure_vmd4_full_frame_area). Tests exercising the VMD4
    area-expansion path override this. This is what the default_vmd_app_mocks
    fixture's 'vmd' app (built-in) triggers by default."""
    full_frame_data = {
        "configurationStatus": 0,
        "profiles": [{
            "camera": 1, "uid": 1, "name": "Profile 1",
            "filters": [],
            "triggers": [{"type": "includeArea", "data": [[-1.0, -1.0], [-1.0, 1.0], [1.0, 1.0], [1.0, -1.0]]}],
        }],
        "cameras": [{"id": 1, "rotation": 0, "active": True}],
    }
    with patch("cctv.reconciler.vapix.get_vmd4_configuration", return_value=full_frame_data) as mock_get, \
         patch("cctv.reconciler.vapix.set_vmd4_configuration") as mock_set:
        yield mock_get, mock_set


def test_reconcile_all_match_returns_no_change(
    camera_config, mock_auth, smb_params_response, motion_params_response,
    storage_params_response, volatile_hostname_response,
) -> None:
    """All settings match → NO_CHANGE, no SET calls."""
    with patch("cctv.reconciler.vapix.get_params") as mock_get, \
         patch("cctv.reconciler.vapix.set_params") as mock_set:
        mock_get.side_effect = [smb_params_response, motion_params_response, storage_params_response, volatile_hostname_response]
        result = reconcile(CAM, camera_config, mock_auth)

    assert result.status == CameraStatus.NO_CHANGE
    assert result.settings_changed == []
    mock_set.assert_not_called()


def test_reconcile_smb_ip_mismatch_sets_only_smb_ip(
    camera_config, mock_auth, smb_params_response, motion_params_response,
    storage_params_response, volatile_hostname_response,
) -> None:
    """SMB host differs → smb_ip in settings_changed, set_params called once for smb_ip only."""
    smb_params_response = {**smb_params_response, _SMB_HOST: "10.0.0.99"}

    with patch("cctv.reconciler.vapix.get_params") as mock_get, \
         patch("cctv.reconciler.vapix.set_params") as mock_set:
        mock_get.side_effect = [smb_params_response, motion_params_response, storage_params_response, volatile_hostname_response]
        result = reconcile(CAM, camera_config, mock_auth)

    assert result.status == CameraStatus.APPLIED
    assert "smb_ip" in result.settings_changed
    assert "smb_creds" not in result.settings_changed
    assert "motion" not in result.settings_changed
    assert "retention" not in result.settings_changed
    assert "hostname" not in result.settings_changed
    mock_set.assert_called_once_with(
        CAM.ip,
        {_SMB_HOST: camera_config.profiles[0].storage.smb.ip},
        mock_auth,
        camera_config.timeout,
    )


def test_reconcile_motion_sensitivity_mismatch(
    camera_config, mock_auth, smb_params_response, motion_params_response,
    storage_params_response, volatile_hostname_response,
) -> None:
    """Motion sensitivity differs → motion in settings_changed, sensitivity SET only."""
    motion_params_response = {**motion_params_response, _MOTION_SENSITIVITY: "99"}

    with patch("cctv.reconciler.vapix.get_params") as mock_get, \
         patch("cctv.reconciler.vapix.set_params") as mock_set:
        mock_get.side_effect = [smb_params_response, motion_params_response, storage_params_response, volatile_hostname_response]
        result = reconcile(CAM, camera_config, mock_auth)

    assert result.status == CameraStatus.APPLIED
    assert "motion" in result.settings_changed
    assert "smb_ip" not in result.settings_changed
    assert "smb_creds" not in result.settings_changed
    assert "retention" not in result.settings_changed
    assert "hostname" not in result.settings_changed
    mock_set.assert_called_once_with(
        CAM.ip,
        {_MOTION_SENSITIVITY: "90"},
        mock_auth,
        camera_config.timeout,
    )


def test_reconcile_smb_ip_already_matches_no_set(
    camera_config, mock_auth, smb_params_response, motion_params_response,
    storage_params_response, volatile_hostname_response,
) -> None:
    """SMB IP matches config → smb_ip NOT in settings_changed, no smb_ip SET."""
    with patch("cctv.reconciler.vapix.get_params") as mock_get, \
         patch("cctv.reconciler.vapix.set_params") as mock_set:
        mock_get.side_effect = [smb_params_response, motion_params_response, storage_params_response, volatile_hostname_response]
        result = reconcile(CAM, camera_config, mock_auth)

    assert "smb_ip" not in result.settings_changed
    for c in mock_set.call_args_list:
        assert _SMB_HOST not in c.args[1]


def test_reconcile_vapix_error_propagates(
    camera_config, mock_auth
) -> None:
    """VapixError from get_params propagates out of reconcile() uncaught."""
    with patch("cctv.reconciler.vapix.get_params", side_effect=VapixError("timeout")):
        with pytest.raises(VapixError, match="timeout"):
            reconcile(CAM, camera_config, mock_auth)


def test_reconcile_returns_camera_result_with_ip_and_model(
    camera_config, mock_auth, smb_params_response, motion_params_response,
    storage_params_response, volatile_hostname_response,
) -> None:
    """Result carries ip and model from DiscoveredCamera."""
    with patch("cctv.reconciler.vapix.get_params") as mock_get, \
         patch("cctv.reconciler.vapix.set_params"):
        mock_get.side_effect = [smb_params_response, motion_params_response, storage_params_response, volatile_hostname_response]
        result = reconcile(CAM, camera_config, mock_auth)

    assert result.ip == "192.168.1.101"
    assert result.model == "AXIS P3245-V"
    assert isinstance(result, CameraResult)


def test_reconcile_smb_share_mismatch_sets_smb_creds(
    camera_config, mock_auth, smb_params_response, motion_params_response,
    storage_params_response, volatile_hostname_response,
) -> None:
    """smb_share differs → smb_creds in settings_changed, set_params called with full creds group."""
    smb_params_response = {**smb_params_response, _SMB_SHARE: "/old/path"}

    with patch("cctv.reconciler.vapix.get_params") as mock_get, \
         patch("cctv.reconciler.vapix.set_params") as mock_set:
        mock_get.side_effect = [smb_params_response, motion_params_response, storage_params_response, volatile_hostname_response]
        result = reconcile(CAM, camera_config, mock_auth)

    assert result.status == CameraStatus.APPLIED
    assert "smb_creds" in result.settings_changed
    assert "smb_ip" not in result.settings_changed
    assert "motion" not in result.settings_changed
    assert "retention" not in result.settings_changed
    assert "hostname" not in result.settings_changed
    mock_set.assert_called_once_with(
        CAM.ip,
        {
            _SMB_SHARE: camera_config.profiles[0].storage.smb.share,
            _SMB_USER: camera_config.profiles[0].storage.smb.username,
            _SMB_PASS: camera_config.profiles[0].storage.smb.password,
        },
        mock_auth,
        camera_config.timeout,
    )


def test_reconcile_smb_username_mismatch_sets_smb_creds(
    camera_config, mock_auth, smb_params_response, motion_params_response,
    storage_params_response, volatile_hostname_response,
) -> None:
    """smb_username differs → smb_creds in settings_changed, no smb_ip SET."""
    smb_params_response = {**smb_params_response, _SMB_USER: "wronguser"}

    with patch("cctv.reconciler.vapix.get_params") as mock_get, \
         patch("cctv.reconciler.vapix.set_params") as mock_set:
        mock_get.side_effect = [smb_params_response, motion_params_response, storage_params_response, volatile_hostname_response]
        result = reconcile(CAM, camera_config, mock_auth)

    assert result.status == CameraStatus.APPLIED
    assert "smb_creds" in result.settings_changed
    assert "smb_ip" not in result.settings_changed
    assert mock_set.call_count >= 1
    for c in mock_set.call_args_list:
        assert _SMB_HOST not in c.args[1]


def test_reconcile_smb_both_ip_and_creds_change(
    camera_config, mock_auth, smb_params_response, motion_params_response,
    storage_params_response, volatile_hostname_response,
) -> None:
    """smb_ip AND smb_share both differ → both labels in settings_changed, set_params called twice."""
    smb_params_response = {
        **smb_params_response,
        _SMB_HOST: "10.0.0.99",
        _SMB_SHARE: "/old/path",
    }

    with patch("cctv.reconciler.vapix.get_params") as mock_get, \
         patch("cctv.reconciler.vapix.set_params") as mock_set:
        mock_get.side_effect = [smb_params_response, motion_params_response, storage_params_response, volatile_hostname_response]
        result = reconcile(CAM, camera_config, mock_auth)

    assert result.status == CameraStatus.APPLIED
    assert "smb_ip" in result.settings_changed
    assert "smb_creds" in result.settings_changed
    assert mock_set.call_count == 2
    mock_set.assert_any_call(
        CAM.ip, {_SMB_HOST: camera_config.profiles[0].storage.smb.ip}, mock_auth, camera_config.timeout
    )
    mock_set.assert_any_call(
        CAM.ip,
        {
            _SMB_SHARE: camera_config.profiles[0].storage.smb.share,
            _SMB_USER: camera_config.profiles[0].storage.smb.username,
            _SMB_PASS: camera_config.profiles[0].storage.smb.password,
        },
        mock_auth,
        camera_config.timeout,
    )


def test_reconcile_smb_ip_matches_creds_differ(
    camera_config, mock_auth, smb_params_response, motion_params_response,
    storage_params_response, volatile_hostname_response,
) -> None:
    """smb_ip matches but smb_password differs → only smb_creds in settings_changed, no smb_ip SET."""
    smb_params_response = {**smb_params_response, _SMB_PASS: "wrongpass"}

    with patch("cctv.reconciler.vapix.get_params") as mock_get, \
         patch("cctv.reconciler.vapix.set_params") as mock_set:
        mock_get.side_effect = [smb_params_response, motion_params_response, storage_params_response, volatile_hostname_response]
        result = reconcile(CAM, camera_config, mock_auth)

    assert result.status == CameraStatus.APPLIED
    assert "smb_creds" in result.settings_changed
    assert "smb_ip" not in result.settings_changed
    assert mock_set.call_count >= 1
    for c in mock_set.call_args_list:
        assert _SMB_HOST not in c.args[1]


def test_reconcile_smb_password_not_in_vapix_error(
    camera_config, mock_auth, smb_params_response, motion_params_response
) -> None:
    """NFR7: smb_password value must not appear in any VapixError message."""
    smb_params_response = {**smb_params_response, _SMB_PASS: "wrongpass"}  # triggers creds SET
    error_msg = "SET params on 192.168.1.101 failed: 401 Unauthorized"
    with patch("cctv.reconciler.vapix.get_params") as mock_get, \
         patch("cctv.reconciler.vapix.set_params", side_effect=VapixError(error_msg)):
        mock_get.side_effect = [smb_params_response, motion_params_response]
        with pytest.raises(VapixError) as exc_info:
            reconcile(CAM, camera_config, mock_auth)
    assert camera_config.profiles[0].storage.smb.password not in str(exc_info.value)


def test_reconcile_motion_sensitivity_differs_sets_only_sensitivity(
    camera_config, mock_auth, smb_params_response, motion_params_response,
    storage_params_response, volatile_hostname_response,
) -> None:
    """Sensitivity differs → SET with sensitivity only; enabled is not written (D3: ActionRules pending)."""
    motion_params_response = {**motion_params_response, _MOTION_SENSITIVITY: "99"}

    with patch("cctv.reconciler.vapix.get_params") as mock_get, \
         patch("cctv.reconciler.vapix.set_params") as mock_set:
        mock_get.side_effect = [smb_params_response, motion_params_response, storage_params_response, volatile_hostname_response]
        result = reconcile(CAM, camera_config, mock_auth)

    assert result.status == CameraStatus.APPLIED
    assert "motion" in result.settings_changed
    assert result.settings_changed.count("motion") == 1
    mock_set.assert_called_once_with(
        CAM.ip,
        {_MOTION_SENSITIVITY: "90"},
        mock_auth,
        camera_config.timeout,
    )


def test_reconcile_motion_enabled_config_not_written(
    camera_config, legacy_profile, mock_auth, smb_params_response, motion_params_response,
    storage_params_response, volatile_hostname_response,
) -> None:
    """D3: config.motion_enabled is never written via param.cgi regardless of camera state."""
    legacy_profile.motion_detection["enabled"] = False
    with patch("cctv.reconciler.vapix.get_params") as mock_get, \
         patch("cctv.reconciler.vapix.set_params") as mock_set:
        mock_get.side_effect = [smb_params_response, motion_params_response, storage_params_response, volatile_hostname_response]
        result = reconcile(CAM, camera_config, mock_auth)

    assert result.status == CameraStatus.NO_CHANGE
    assert "motion" not in result.settings_changed
    mock_set.assert_not_called()


def test_reconcile_motion_already_matches_no_motion_set(
    camera_config, mock_auth, smb_params_response, motion_params_response,
    storage_params_response, volatile_hostname_response,
) -> None:
    """motion group matches config → 'motion' not in settings_changed, no motion SET calls."""
    with patch("cctv.reconciler.vapix.get_params") as mock_get, \
         patch("cctv.reconciler.vapix.set_params") as mock_set:
        mock_get.side_effect = [smb_params_response, motion_params_response, storage_params_response, volatile_hostname_response]
        result = reconcile(CAM, camera_config, mock_auth)

    assert result.status == CameraStatus.NO_CHANGE
    assert "motion" not in result.settings_changed
    mock_set.assert_not_called()


def test_reconcile_motion_sensitivity_float_treated_as_int(
    camera_config, legacy_profile, mock_auth, smb_params_response, motion_params_response,
    storage_params_response, volatile_hostname_response,
) -> None:
    """Float motion_sensitivity (e.g. 90.0) must compare as '90', not '90.0'."""
    legacy_profile.motion_detection["sensitivity"] = 90.0
    with patch("cctv.reconciler.vapix.get_params") as mock_get, \
         patch("cctv.reconciler.vapix.set_params") as mock_set:
        mock_get.side_effect = [smb_params_response, motion_params_response, storage_params_response, volatile_hostname_response]
        result = reconcile(CAM, camera_config, mock_auth)

    assert result.status == CameraStatus.NO_CHANGE
    assert "motion" not in result.settings_changed
    mock_set.assert_not_called()


def test_reconcile_installs_vmd_app_when_absent(
    camera_config, legacy_profile, mock_auth, smb_params_response, motion_params_response,
    storage_params_response, volatile_hostname_response,
) -> None:
    """vmd app not in the installed-apps list → uploaded, re-listed, then started under its real package Name.

    Regression test: the legacy 2.2.1 .eap installs under package Name
    "VideoMotionDetection", not "vmd" (confirmed against a real AXIS M3005) —
    start_application must use whatever Name shows up after install, not a
    hardcoded constant.
    """
    from cctv.vapix import InstalledApplication
    legacy_profile.applications["video_motion_detection"] = {"app_package_path": "/opt/eap/AXIS_Video_Motion_Detection_2_2_1.eap"}
    installed_after_upload = InstalledApplication(
        name="VideoMotionDetection", nice_name="AXIS Video Motion Detection", status="Stopped",
    )

    with patch("cctv.reconciler.vapix.get_params") as mock_get, \
         patch("cctv.reconciler.vapix.set_params"), \
         patch("cctv.reconciler.vapix.get_applications", side_effect=[[], [installed_after_upload]]) as mock_get_apps, \
         patch("cctv.reconciler.vapix.upload_application") as mock_upload, \
         patch("cctv.reconciler.vapix.start_application") as mock_start:
        mock_get.side_effect = [smb_params_response, motion_params_response, storage_params_response, volatile_hostname_response]
        result = reconcile(CAM, camera_config, mock_auth)

    assert "motion_app_installed" in result.settings_changed
    assert mock_get_apps.call_count == 2
    mock_upload.assert_called_once_with(CAM.ip, mock_auth, camera_config.timeout, "/opt/eap/AXIS_Video_Motion_Detection_2_2_1.eap")
    mock_start.assert_called_once_with(CAM.ip, mock_auth, camera_config.timeout, "VideoMotionDetection")


def test_reconcile_vmd_app_missing_after_upload_raises(
    camera_config, legacy_profile, mock_auth, smb_params_response,
) -> None:
    """Uploaded package but app still doesn't show up in the list afterwards → clear VapixError, no start attempted."""
    legacy_profile.applications["video_motion_detection"] = {"app_package_path": "/opt/eap/broken.eap"}

    with patch("cctv.reconciler.vapix.get_params", return_value=smb_params_response), \
         patch("cctv.reconciler.vapix.get_applications", return_value=[]), \
         patch("cctv.reconciler.vapix.upload_application") as mock_upload, \
         patch("cctv.reconciler.vapix.start_application") as mock_start:
        with pytest.raises(VapixError, match="Uploaded .* but no AXIS Video Motion Detection app appeared"):
            reconcile(CAM, camera_config, mock_auth)

    mock_upload.assert_called_once()
    mock_start.assert_not_called()


def test_reconcile_missing_vmd_app_without_package_path_raises(
    camera_config, legacy_profile, mock_auth, smb_params_response,
) -> None:
    """vmd app absent and no app_package_path configured → clear VapixError, no upload/start attempted."""
    legacy_profile.applications.pop("video_motion_detection", None)

    with patch("cctv.reconciler.vapix.get_params", return_value=smb_params_response), \
         patch("cctv.reconciler.vapix.get_applications", return_value=[]), \
         patch("cctv.reconciler.vapix.upload_application") as mock_upload, \
         patch("cctv.reconciler.vapix.start_application") as mock_start:
        with pytest.raises(VapixError, match="app_package_path"):
            reconcile(CAM, camera_config, mock_auth)

    mock_upload.assert_not_called()
    mock_start.assert_not_called()


def test_reconcile_starts_stopped_vmd_app(
    camera_config, mock_auth, smb_params_response, motion_params_response,
    storage_params_response, volatile_hostname_response,
) -> None:
    """vmd app installed but Status=Stopped → started, not re-uploaded."""
    from cctv.vapix import InstalledApplication
    stopped_app = InstalledApplication(name="vmd", nice_name="AXIS Video Motion Detection", status="Stopped")

    with patch("cctv.reconciler.vapix.get_params") as mock_get, \
         patch("cctv.reconciler.vapix.set_params"), \
         patch("cctv.reconciler.vapix.get_applications", return_value=[stopped_app]), \
         patch("cctv.reconciler.vapix.upload_application") as mock_upload, \
         patch("cctv.reconciler.vapix.start_application") as mock_start:
        mock_get.side_effect = [smb_params_response, motion_params_response, storage_params_response, volatile_hostname_response]
        result = reconcile(CAM, camera_config, mock_auth)

    assert "motion_app_started" in result.settings_changed
    assert "motion_app_installed" not in result.settings_changed
    mock_upload.assert_not_called()
    mock_start.assert_called_once_with(CAM.ip, mock_auth, camera_config.timeout, "vmd")


def test_reconcile_vmd_app_idle_status_no_change(
    camera_config, mock_auth, smb_params_response, motion_params_response,
    storage_params_response, volatile_hostname_response,
) -> None:
    """Regression: legacy VMD 2.2.1 settles into Status=Idle once started — must NOT
    be treated as stopped and re-started on every reconcile (confirmed on a real M3005)."""
    from cctv.vapix import InstalledApplication
    idle_app = InstalledApplication(name="VideoMotionDetection", nice_name="AXIS Video Motion Detection", status="Idle")

    with patch("cctv.reconciler.vapix.get_params") as mock_get, \
         patch("cctv.reconciler.vapix.set_params"), \
         patch("cctv.reconciler.vapix.get_applications", return_value=[idle_app]), \
         patch("cctv.reconciler.vapix.upload_application") as mock_upload, \
         patch("cctv.reconciler.vapix.start_application") as mock_start:
        mock_get.side_effect = [smb_params_response, motion_params_response, storage_params_response, volatile_hostname_response]
        result = reconcile(CAM, camera_config, mock_auth)

    assert "motion_app_started" not in result.settings_changed
    assert "motion_app_installed" not in result.settings_changed
    mock_upload.assert_not_called()
    mock_start.assert_not_called()


def test_reconcile_vmd_app_check_skipped_when_motion_disabled(
    camera_config, legacy_profile, mock_auth, smb_params_response, motion_params_response,
    storage_params_response, volatile_hostname_response,
) -> None:
    """motion_enabled=False → app install/start check is not even attempted."""
    legacy_profile.motion_detection["enabled"] = False

    with patch("cctv.reconciler.vapix.get_params") as mock_get, \
         patch("cctv.reconciler.vapix.set_params"), \
         patch("cctv.reconciler.vapix.get_applications") as mock_get_apps:
        mock_get.side_effect = [smb_params_response, motion_params_response, storage_params_response, volatile_hostname_response]
        result = reconcile(CAM, camera_config, mock_auth)

    assert "motion_app_installed" not in result.settings_changed
    assert "motion_app_started" not in result.settings_changed
    mock_get_apps.assert_not_called()


# ---------------------------------------------------------------------------
# Legacy VMD app's own detection area (separate from root.Motion)
# ---------------------------------------------------------------------------


def test_reconcile_expands_vmd_app_area_when_not_full_frame(
    camera_config, mock_auth, smb_params_response, motion_params_response,
    storage_params_response, volatile_hostname_response,
) -> None:
    """Real-hardware finding (2026-08-04): legacy app's factory-default 'Detection
    Area' covers only ~60% (centered) → expanded to full-frame, 'motion_app_area'
    in settings_changed."""
    from cctv.vapix import InstalledApplication, VmdAppArea
    legacy_app = InstalledApplication(name="VideoMotionDetection", nice_name="AXIS Video Motion Detection", status="Running")
    default_area = [VmdAppArea(name="Detection Area", points=[(0.6, 0.6), (0.6, -0.6), (-0.6, -0.6), (-0.6, 0.6)])]

    with patch("cctv.reconciler.vapix.get_params") as mock_get, \
         patch("cctv.reconciler.vapix.set_params"), \
         patch("cctv.reconciler.vapix.get_applications", return_value=[legacy_app]), \
         patch("cctv.reconciler.vapix.get_vmd_app_config", return_value=default_area), \
         patch("cctv.reconciler.vapix.set_vmd_app_config") as mock_set_area:
        mock_get.side_effect = [smb_params_response, motion_params_response, storage_params_response, volatile_hostname_response]
        result = reconcile(CAM, camera_config, mock_auth)

    assert "motion_app_area" in result.settings_changed
    mock_set_area.assert_called_once_with(
        CAM.ip, mock_auth, camera_config.timeout, "VideoMotionDetection",
        [VmdAppArea(name="Detection Area", points=[(1.0, 1.0), (1.0, -1.0), (-1.0, -1.0), (-1.0, 1.0)])],
    )


def test_reconcile_vmd_app_area_already_full_frame_no_change(
    camera_config, mock_auth, smb_params_response, motion_params_response,
    storage_params_response, volatile_hostname_response,
) -> None:
    """Area already full-frame → no SET call, 'motion_app_area' not in settings_changed."""
    from cctv.vapix import InstalledApplication, VmdAppArea
    legacy_app = InstalledApplication(name="VideoMotionDetection", nice_name="AXIS Video Motion Detection", status="Running")
    full_frame_area = [VmdAppArea(name="Detection Area", points=[(1.0, 1.0), (1.0, -1.0), (-1.0, -1.0), (-1.0, 1.0)])]

    with patch("cctv.reconciler.vapix.get_params") as mock_get, \
         patch("cctv.reconciler.vapix.set_params"), \
         patch("cctv.reconciler.vapix.get_applications", return_value=[legacy_app]), \
         patch("cctv.reconciler.vapix.get_vmd_app_config", return_value=full_frame_area), \
         patch("cctv.reconciler.vapix.set_vmd_app_config") as mock_set_area:
        mock_get.side_effect = [smb_params_response, motion_params_response, storage_params_response, volatile_hostname_response]
        result = reconcile(CAM, camera_config, mock_auth)

    assert "motion_app_area" not in result.settings_changed
    mock_set_area.assert_not_called()


def test_reconcile_vmd_app_area_skipped_for_builtin_app(
    camera_config, mock_auth, smb_params_response, motion_params_response,
    storage_params_response, volatile_hostname_response,
) -> None:
    """Built-in 'vmd' app (VMD3/VMD4) → the LEGACY area functions are never
    called (it uses the separate VMD4 API instead — see the VMD4-specific
    tests below)."""
    with patch("cctv.reconciler.vapix.get_params") as mock_get, \
         patch("cctv.reconciler.vapix.set_params"), \
         patch("cctv.reconciler.vapix.get_vmd_app_config") as mock_get_area, \
         patch("cctv.reconciler.vapix.set_vmd_app_config") as mock_set_area:
        # default_vmd_app_mocks autouse fixture returns name="vmd" (built-in)
        mock_get.side_effect = [smb_params_response, motion_params_response, storage_params_response, volatile_hostname_response]
        result = reconcile(CAM, camera_config, mock_auth)

    assert "motion_app_area" not in result.settings_changed  # default_vmd4_area_mocks fixture is already full-frame
    mock_get_area.assert_not_called()
    mock_set_area.assert_not_called()


def test_reconcile_vmd_app_area_skipped_when_motion_disabled(
    camera_config, legacy_profile, mock_auth, smb_params_response, motion_params_response,
    storage_params_response, volatile_hostname_response,
) -> None:
    """motion_enabled=False → neither area API is even attempted."""
    legacy_profile.motion_detection["enabled"] = False

    with patch("cctv.reconciler.vapix.get_params") as mock_get, \
         patch("cctv.reconciler.vapix.set_params"), \
         patch("cctv.reconciler.vapix.get_vmd_app_config") as mock_get_area, \
         patch("cctv.reconciler.vapix.get_vmd4_configuration") as mock_get_vmd4:
        mock_get.side_effect = [smb_params_response, motion_params_response, storage_params_response, volatile_hostname_response]
        reconcile(CAM, camera_config, mock_auth)

    mock_get_area.assert_not_called()
    mock_get_vmd4.assert_not_called()


def test_reconcile_expands_vmd4_area_when_not_full_frame(
    camera_config, mock_auth, smb_params_response, motion_params_response,
    storage_params_response, volatile_hostname_response,
) -> None:
    """Real-hardware finding (2026-08-04, AXIS M3085-V 192.168.1.72): the built-in
    VMD4 app's default profile covers only ~97% of the frame → expanded to
    full-frame via the official setConfiguration API, 'motion_app_area' in
    settings_changed, filters/uid/name preserved unchanged."""
    almost_full = {
        "configurationStatus": 0,
        "profiles": [{
            "camera": 1, "uid": 1, "name": "Profile 1",
            "filters": [{"active": True, "data": [5, 5], "type": "sizePercentage"}],
            "triggers": [{"type": "includeArea", "data": [[-0.97, -0.97], [-0.97, 0.97], [0.97, 0.97], [0.97, -0.97]]}],
        }],
        "cameras": [{"id": 1, "rotation": 0, "active": True}],
    }
    with patch("cctv.reconciler.vapix.get_params") as mock_get, \
         patch("cctv.reconciler.vapix.set_params"), \
         patch("cctv.reconciler.vapix.get_vmd4_configuration", return_value=almost_full), \
         patch("cctv.reconciler.vapix.set_vmd4_configuration") as mock_set_vmd4:
        mock_get.side_effect = [smb_params_response, motion_params_response, storage_params_response, volatile_hostname_response]
        result = reconcile(CAM, camera_config, mock_auth)

    assert "motion_app_area" in result.settings_changed
    mock_set_vmd4.assert_called_once()
    args, _ = mock_set_vmd4.call_args
    posted_data = args[3]
    assert posted_data["profiles"][0]["triggers"][0]["data"] == [[-1.0, -1.0], [-1.0, 1.0], [1.0, 1.0], [1.0, -1.0]]
    assert posted_data["profiles"][0]["filters"] == [{"active": True, "data": [5, 5], "type": "sizePercentage"}]
    assert posted_data["profiles"][0]["uid"] == 1
    assert posted_data["profiles"][0]["name"] == "Profile 1"


def test_reconcile_vmd4_area_already_full_frame_no_change(
    camera_config, mock_auth, smb_params_response, motion_params_response,
    storage_params_response, volatile_hostname_response,
) -> None:
    """Profile already full-frame → no SET call, 'motion_app_area' not in settings_changed."""
    full_frame = {
        "configurationStatus": 0,
        "profiles": [{
            "camera": 1, "uid": 1, "name": "Profile 1", "filters": [],
            "triggers": [{"type": "includeArea", "data": [[-1.0, -1.0], [-1.0, 1.0], [1.0, 1.0], [1.0, -1.0]]}],
        }],
        "cameras": [{"id": 1, "rotation": 0, "active": True}],
    }
    with patch("cctv.reconciler.vapix.get_params") as mock_get, \
         patch("cctv.reconciler.vapix.set_params"), \
         patch("cctv.reconciler.vapix.get_vmd4_configuration", return_value=full_frame), \
         patch("cctv.reconciler.vapix.set_vmd4_configuration") as mock_set_vmd4:
        mock_get.side_effect = [smb_params_response, motion_params_response, storage_params_response, volatile_hostname_response]
        result = reconcile(CAM, camera_config, mock_auth)

    assert "motion_app_area" not in result.settings_changed
    mock_set_vmd4.assert_not_called()


def test_reconcile_vmd4_no_profiles_no_change(
    camera_config, mock_auth, smb_params_response, motion_params_response,
    storage_params_response, volatile_hostname_response,
) -> None:
    """No profiles configured at all → nothing to expand, no crash, no SET call."""
    empty = {"configurationStatus": 0, "profiles": [], "cameras": []}
    with patch("cctv.reconciler.vapix.get_params") as mock_get, \
         patch("cctv.reconciler.vapix.set_params"), \
         patch("cctv.reconciler.vapix.get_vmd4_configuration", return_value=empty), \
         patch("cctv.reconciler.vapix.set_vmd4_configuration") as mock_set_vmd4:
        mock_get.side_effect = [smb_params_response, motion_params_response, storage_params_response, volatile_hostname_response]
        result = reconcile(CAM, camera_config, mock_auth)

    assert "motion_app_area" not in result.settings_changed
    mock_set_vmd4.assert_not_called()


def test_reconcile_motion_skipped_when_group_absent(
    camera_config, mock_auth, smb_params_response, storage_params_response,
    volatile_hostname_response,
) -> None:
    """Models without root.Motion group (e.g. M3005) must not trigger a motion SET."""
    with patch("cctv.reconciler.vapix.get_params") as mock_get, \
         patch("cctv.reconciler.vapix.set_params") as mock_set:
        mock_get.side_effect = [smb_params_response, {}, storage_params_response, volatile_hostname_response]
        result = reconcile(CAM, camera_config, mock_auth)

    assert "motion" not in result.settings_changed
    mock_set.assert_not_called()


def test_reconcile_adds_full_frame_window_when_absent(
    camera_config, mock_auth, smb_params_response, storage_params_response,
    volatile_hostname_response,
) -> None:
    """No full-frame window exists → add_motion_window called, 'motion_window' in settings_changed."""
    no_fullframe = {
        "root.Motion.M0.Name": "DefaultWindow",
        "root.Motion.M0.Left": "200",
        "root.Motion.M0.Right": "4000",
        "root.Motion.M0.Top": "200",
        "root.Motion.M0.Bottom": "4000",
        "root.Motion.M0.Sensitivity": "50",
    }
    full_frame_after = {
        **no_fullframe,
        "root.Motion.M1.Name": "full_frame",
        "root.Motion.M1.Left": "0",
        "root.Motion.M1.Right": "9999",
        "root.Motion.M1.Top": "0",
        "root.Motion.M1.Bottom": "9999",
        "root.Motion.M1.Sensitivity": "50",
    }
    with patch("cctv.reconciler.vapix.get_params") as mock_get, \
         patch("cctv.reconciler.vapix.set_params"), \
         patch("cctv.reconciler.vapix.add_motion_window", return_value=1) as mock_add_win:
        # SMB, first motion read (no full-frame), second motion read (after window added), storage, volatile
        mock_get.side_effect = [smb_params_response, no_fullframe, full_frame_after, storage_params_response, volatile_hostname_response]
        result = reconcile(CAM, camera_config, mock_auth)

    assert "motion_window" in result.settings_changed
    mock_add_win.assert_called_once_with(CAM.ip, mock_auth, camera_config.timeout, 90)


def test_reconcile_no_window_added_when_fullframe_exists(
    camera_config, mock_auth, smb_params_response, motion_params_response,
    storage_params_response, volatile_hostname_response,
) -> None:
    """Full-frame window already exists → add_motion_window NOT called."""
    with patch("cctv.reconciler.vapix.get_params") as mock_get, \
         patch("cctv.reconciler.vapix.set_params"), \
         patch("cctv.reconciler.vapix.add_motion_window") as mock_add_win:
        mock_get.side_effect = [smb_params_response, motion_params_response, storage_params_response, volatile_hostname_response]
        result = reconcile(CAM, camera_config, mock_auth)

    assert "motion_window" not in result.settings_changed
    mock_add_win.assert_not_called()


def test_reconcile_action_rule_uses_full_frame_window_id(
    camera_config, mock_auth, smb_params_response, storage_params_response,
    volatile_hostname_response,
) -> None:
    """When full-frame window is M1 (window_id=1), action rule is created with window=1 filter."""
    m1_fullframe = {
        "root.Motion.M0.Name": "DefaultWindow",
        "root.Motion.M0.Left": "200", "root.Motion.M0.Right": "4000",
        "root.Motion.M0.Top": "200", "root.Motion.M0.Bottom": "4000",
        "root.Motion.M0.Sensitivity": "50",
        "root.Motion.M1.Name": "full_frame",
        "root.Motion.M1.Left": "0", "root.Motion.M1.Right": "9999",
        "root.Motion.M1.Top": "0", "root.Motion.M1.Bottom": "9999",
        "root.Motion.M1.Sensitivity": "50",
    }
    with patch("cctv.reconciler.vapix.get_params") as mock_get, \
         patch("cctv.reconciler.vapix.set_params"), \
         patch("cctv.reconciler.vapix.get_action_configurations", return_value=[]), \
         patch("cctv.reconciler.vapix.get_action_rules", return_value=[]), \
         patch("cctv.reconciler.vapix.add_action_configuration", return_value=7), \
         patch("cctv.reconciler.vapix.add_action_rule") as mock_add_rule:
        mock_get.side_effect = [smb_params_response, m1_fullframe, storage_params_response, volatile_hostname_response]
        reconcile(CAM, camera_config, mock_auth)

    _, kwargs = mock_add_rule.call_args
    message_filter = kwargs["message_filter"]
    assert 'window" and @Value="1"' in message_filter


# ---------------------------------------------------------------------------
# Recording retention
# ---------------------------------------------------------------------------


def test_reconcile_retention_mismatch_sets_retention(
    camera_config, mock_auth, smb_params_response, motion_params_response,
    storage_params_response, volatile_hostname_response,
) -> None:
    """retention_days differs → 'retention' in settings_changed, SET with new value."""
    storage_params_response = {**storage_params_response, _STORAGE_RETENTION_S1: "7"}  # camera has 7, config=33

    with patch("cctv.reconciler.vapix.get_params") as mock_get, \
         patch("cctv.reconciler.vapix.set_params") as mock_set:
        mock_get.side_effect = [smb_params_response, motion_params_response, storage_params_response, volatile_hostname_response]
        result = reconcile(CAM, camera_config, mock_auth)

    assert result.status == CameraStatus.APPLIED
    assert "retention" in result.settings_changed
    assert "smb_ip" not in result.settings_changed
    assert "motion" not in result.settings_changed
    assert "hostname" not in result.settings_changed
    mock_set.assert_called_once_with(
        CAM.ip,
        {_STORAGE_RETENTION_S1: "33"},
        mock_auth,
        camera_config.timeout,
    )


def test_reconcile_retention_already_matches_no_set(
    camera_config, mock_auth, smb_params_response, motion_params_response,
    storage_params_response, volatile_hostname_response,
) -> None:
    """retention_days matches config → 'retention' NOT in settings_changed, no SET."""
    with patch("cctv.reconciler.vapix.get_params") as mock_get, \
         patch("cctv.reconciler.vapix.set_params") as mock_set:
        mock_get.side_effect = [smb_params_response, motion_params_response, storage_params_response, volatile_hostname_response]
        result = reconcile(CAM, camera_config, mock_auth)

    assert "retention" not in result.settings_changed
    mock_set.assert_not_called()


def test_reconcile_retention_applied_label_in_output(
    camera_config, mock_auth, smb_params_response, motion_params_response,
    storage_params_response, volatile_hostname_response,
) -> None:
    """When retention changes, settings_changed contains exactly 'retention' once."""
    storage_params_response = {**storage_params_response, _STORAGE_RETENTION_S1: "90"}

    with patch("cctv.reconciler.vapix.get_params") as mock_get, \
         patch("cctv.reconciler.vapix.set_params"):
        mock_get.side_effect = [smb_params_response, motion_params_response, storage_params_response, volatile_hostname_response]
        result = reconcile(CAM, camera_config, mock_auth)

    assert result.settings_changed.count("retention") == 1


# ---------------------------------------------------------------------------
# Time settings (timezone + NTP)
# ---------------------------------------------------------------------------


def test_reconcile_timezone_set_when_differs(
    camera_config, mock_auth, smb_params_response, motion_params_response,
    storage_params_response, time_params_response, volatile_hostname_response,
) -> None:
    """Timezone in config differs from camera → SET called, 'timezone' in settings_changed."""
    camera_config.timezone = "CET-1CEST,M3.5.0,M10.5.0/3"
    # time_params_response has UTC0 — differs from config

    with patch("cctv.reconciler.vapix.get_params") as mock_get, \
         patch("cctv.reconciler.vapix.set_params") as mock_set:
        mock_get.side_effect = [smb_params_response, motion_params_response, storage_params_response, time_params_response, volatile_hostname_response]
        result = reconcile(CAM, camera_config, mock_auth)

    assert "timezone" in result.settings_changed
    assert result.status == CameraStatus.APPLIED
    mock_set.assert_called_once_with(
        CAM.ip,
        {_TIME_TIMEZONE: "CET-1CEST,M3.5.0,M10.5.0/3"},
        mock_auth,
        camera_config.timeout,
    )


def test_reconcile_timezone_no_change_when_matches(
    camera_config, mock_auth, smb_params_response, motion_params_response,
    storage_params_response, time_params_response, volatile_hostname_response,
) -> None:
    """Timezone matches camera value → no SET, 'timezone' not in settings_changed."""
    camera_config.timezone = "UTC0"
    # time_params_response already has UTC0

    with patch("cctv.reconciler.vapix.get_params") as mock_get, \
         patch("cctv.reconciler.vapix.set_params") as mock_set:
        mock_get.side_effect = [smb_params_response, motion_params_response, storage_params_response, time_params_response, volatile_hostname_response]
        result = reconcile(CAM, camera_config, mock_auth)

    assert "timezone" not in result.settings_changed
    mock_set.assert_not_called()


def test_reconcile_time_skipped_when_not_configured(
    camera_config, mock_auth, smb_params_response, motion_params_response,
    storage_params_response, volatile_hostname_response,
) -> None:
    """No timezone in config → root.Time group never read."""
    # camera_config has no timezone by default
    with patch("cctv.reconciler.vapix.get_params") as mock_get, \
         patch("cctv.reconciler.vapix.set_params") as mock_set:
        mock_get.side_effect = [smb_params_response, motion_params_response, storage_params_response, volatile_hostname_response]
        result = reconcile(CAM, camera_config, mock_auth)

    assert "timezone" not in result.settings_changed
    assert mock_get.call_count == 4  # smb, motion, storage, volatile — no time call


# ---------------------------------------------------------------------------
# Hostname sync
# ---------------------------------------------------------------------------


def test_reconcile_hostname_synced_when_volatile_differs(
    camera_config, mock_auth, smb_params_response, motion_params_response,
    storage_params_response,
) -> None:
    """Volatile hostname set and differs from static → static updated, 'hostname' in settings_changed."""
    volatile = {
        "root.Network.VolatileHostName.HostName": "axis-repo",
        "root.Network.VolatileHostName.ObtainFromDHCP": "yes",
    }
    static = {_NETWORK_HOSTNAME: "axis-00408ce2767e"}

    with patch("cctv.reconciler.vapix.get_params") as mock_get, \
         patch("cctv.reconciler.vapix.set_params") as mock_set:
        mock_get.side_effect = [smb_params_response, motion_params_response, storage_params_response, volatile, static]
        result = reconcile(CAM, camera_config, mock_auth)

    assert "hostname" in result.settings_changed
    assert result.status == CameraStatus.APPLIED
    mock_set.assert_called_once_with(
        CAM.ip,
        {_NETWORK_HOSTNAME: "axis-repo"},
        mock_auth,
        camera_config.timeout,
    )


def test_reconcile_hostname_not_synced_when_volatile_empty(
    camera_config, mock_auth, smb_params_response, motion_params_response,
    storage_params_response, volatile_hostname_response,
) -> None:
    """Volatile hostname empty (no DHCP name) → no hostname update, static get_params not called."""
    with patch("cctv.reconciler.vapix.get_params") as mock_get, \
         patch("cctv.reconciler.vapix.set_params") as mock_set:
        mock_get.side_effect = [smb_params_response, motion_params_response, storage_params_response, volatile_hostname_response]
        result = reconcile(CAM, camera_config, mock_auth)

    assert "hostname" not in result.settings_changed
    mock_set.assert_not_called()
    assert mock_get.call_count == 4  # smb, motion, storage, volatile — no 5th call for static


def test_reconcile_hostname_no_change_when_already_synced(
    camera_config, mock_auth, smb_params_response, motion_params_response,
    storage_params_response,
) -> None:
    """Volatile hostname matches static → no SET call, 'hostname' not in settings_changed."""
    volatile = {
        "root.Network.VolatileHostName.HostName": "axis-repo",
        "root.Network.VolatileHostName.ObtainFromDHCP": "yes",
    }
    static = {_NETWORK_HOSTNAME: "axis-repo"}  # already synced

    with patch("cctv.reconciler.vapix.get_params") as mock_get, \
         patch("cctv.reconciler.vapix.set_params") as mock_set:
        mock_get.side_effect = [smb_params_response, motion_params_response, storage_params_response, volatile, static]
        result = reconcile(CAM, camera_config, mock_auth)

    assert "hostname" not in result.settings_changed
    mock_set.assert_not_called()


# ---------------------------------------------------------------------------
# Motion action rule
# ---------------------------------------------------------------------------


def test_reconcile_creates_motion_rule_when_absent(
    camera_config, mock_auth, smb_params_response, motion_params_response,
    storage_params_response, volatile_hostname_response, motion_action_config,
) -> None:
    """No motion rule on camera → rule created, 'motion_rule' in settings_changed."""
    with patch("cctv.reconciler.vapix.get_params") as mock_get, \
         patch("cctv.reconciler.vapix.set_params"), \
         patch("cctv.reconciler.vapix.get_action_configurations", return_value=[]), \
         patch("cctv.reconciler.vapix.get_action_rules", return_value=[]), \
         patch("cctv.reconciler.vapix.add_action_configuration", return_value=5) as mock_add_cfg, \
         patch("cctv.reconciler.vapix.add_action_rule") as mock_add_rule:
        mock_get.side_effect = [smb_params_response, motion_params_response, storage_params_response, volatile_hostname_response]
        result = reconcile(CAM, camera_config, mock_auth)

    assert "motion_rule" in result.settings_changed
    assert result.status == CameraStatus.APPLIED
    mock_add_cfg.assert_called_once()
    mock_add_rule.assert_called_once()
    # rule must point at the newly created config id (primary_action=5)
    args, kwargs = mock_add_rule.call_args
    primary = kwargs.get("primary_action") if "primary_action" in kwargs else args[6]
    assert primary == 5


def test_reconcile_no_change_when_motion_rule_exists(
    camera_config, mock_auth, smb_params_response, motion_params_response,
    storage_params_response, volatile_hostname_response, motion_action_config, motion_action_rule,
) -> None:
    """Motion recording rule already present → 'motion_rule' NOT in settings_changed."""
    with patch("cctv.reconciler.vapix.get_params") as mock_get, \
         patch("cctv.reconciler.vapix.set_params"), \
         patch("cctv.reconciler.vapix.get_action_configurations", return_value=[motion_action_config]), \
         patch("cctv.reconciler.vapix.get_action_rules", return_value=[motion_action_rule]), \
         patch("cctv.reconciler.vapix.add_action_configuration") as mock_add_cfg, \
         patch("cctv.reconciler.vapix.add_action_rule") as mock_add_rule:
        mock_get.side_effect = [smb_params_response, motion_params_response, storage_params_response, volatile_hostname_response]
        result = reconcile(CAM, camera_config, mock_auth)

    assert "motion_rule" not in result.settings_changed
    mock_add_cfg.assert_not_called()
    mock_add_rule.assert_not_called()


def test_reconcile_motion_rule_skipped_when_motion_disabled(
    camera_config, legacy_profile, mock_auth, smb_params_response, motion_params_response,
    storage_params_response, volatile_hostname_response,
) -> None:
    """motion_enabled=False → no SOAP calls at all for action rules."""
    legacy_profile.motion_detection["enabled"] = False
    with patch("cctv.reconciler.vapix.get_params") as mock_get, \
         patch("cctv.reconciler.vapix.set_params"), \
         patch("cctv.reconciler.vapix.get_action_configurations") as mock_get_cfgs, \
         patch("cctv.reconciler.vapix.get_action_rules") as mock_get_rules:
        mock_get.side_effect = [smb_params_response, motion_params_response, storage_params_response, volatile_hostname_response]
        result = reconcile(CAM, camera_config, mock_auth)

    assert "motion_rule" not in result.settings_changed
    mock_get_cfgs.assert_not_called()
    mock_get_rules.assert_not_called()


def test_reconcile_disabled_rule_not_counted_as_existing(
    camera_config, mock_auth, smb_params_response, motion_params_response,
    storage_params_response, volatile_hostname_response, motion_action_config, motion_action_rule,
) -> None:
    """A disabled motion rule must not satisfy the check — new rule should be created."""
    from cctv.vapix import ActionRule
    disabled_rule = ActionRule(
        rule_id=motion_action_rule.rule_id,
        name=motion_action_rule.name,
        enabled=False,
        topic=motion_action_rule.topic,
        primary_action=motion_action_rule.primary_action,
    )
    with patch("cctv.reconciler.vapix.get_params") as mock_get, \
         patch("cctv.reconciler.vapix.set_params"), \
         patch("cctv.reconciler.vapix.get_action_configurations", return_value=[motion_action_config]), \
         patch("cctv.reconciler.vapix.get_action_rules", return_value=[disabled_rule]), \
         patch("cctv.reconciler.vapix.add_action_configuration", return_value=9), \
         patch("cctv.reconciler.vapix.add_action_rule") as mock_add_rule:
        mock_get.side_effect = [smb_params_response, motion_params_response, storage_params_response, volatile_hostname_response]
        result = reconcile(CAM, camera_config, mock_auth)

    assert "motion_rule" in result.settings_changed
    mock_add_rule.assert_called_once()


def test_reconcile_motion_timing_updated_when_differs(
    camera_config, legacy_profile, mock_auth, smb_params_response, motion_params_response,
    storage_params_response, volatile_hostname_response,
) -> None:
    """Existing rule has wrong durations → old rule/config removed, new one created."""
    from cctv.vapix import ActionConfiguration, ActionRule
    old_cfg = ActionConfiguration(
        config_id=3,
        name="cctv_motion_record",
        template_token="com.axis.action.unlimited.recording.storage",
        parameters={"storage_id": "NetworkShare", "pre_duration": "2000", "post_duration": "2000", "stream_options": ""},
    )
    old_rule = ActionRule(rule_id=3, name="cctv_motion_record", enabled=True,
                          topic="tns1:VideoAnalytics/tnsaxis:MotionDetection", primary_action=3)
    legacy_profile.motion_detection["pre_trigger_time"] = 10
    legacy_profile.motion_detection["post_trigger_time"] = 10

    with patch("cctv.reconciler.vapix.get_params") as mock_get, \
         patch("cctv.reconciler.vapix.set_params"), \
         patch("cctv.reconciler.vapix.get_action_configurations", return_value=[old_cfg]), \
         patch("cctv.reconciler.vapix.get_action_rules", return_value=[old_rule]), \
         patch("cctv.reconciler.vapix.remove_action_rule") as mock_rm_rule, \
         patch("cctv.reconciler.vapix.remove_action_configuration") as mock_rm_cfg, \
         patch("cctv.reconciler.vapix.add_action_configuration", return_value=9) as mock_add_cfg, \
         patch("cctv.reconciler.vapix.add_action_rule") as mock_add_rule:
        mock_get.side_effect = [smb_params_response, motion_params_response, storage_params_response, volatile_hostname_response]
        result = reconcile(CAM, camera_config, mock_auth)

    assert "motion_rule" in result.settings_changed
    mock_rm_rule.assert_called_once_with(CAM.ip, mock_auth, camera_config.timeout, 3)
    mock_rm_cfg.assert_called_once_with(CAM.ip, mock_auth, camera_config.timeout, 3)
    mock_add_cfg.assert_called_once()
    _, kwargs = mock_add_cfg.call_args
    assert kwargs["parameters"]["pre_duration"] == "10000"
    assert kwargs["parameters"]["post_duration"] == "10000"
    mock_add_rule.assert_called_once()


def test_reconcile_motion_timing_no_change_when_matches(
    camera_config, mock_auth, smb_params_response, motion_params_response,
    storage_params_response, volatile_hostname_response, motion_action_config, motion_action_rule,
) -> None:
    """Existing rule has correct durations (5 s default) → no remove/recreate."""
    # motion_action_config fixture has pre_duration=5000, post_duration=5000
    # camera_config defaults to motion_pre_trigger_time=5, motion_post_trigger_time=5
    with patch("cctv.reconciler.vapix.get_params") as mock_get, \
         patch("cctv.reconciler.vapix.set_params"), \
         patch("cctv.reconciler.vapix.get_action_configurations", return_value=[motion_action_config]), \
         patch("cctv.reconciler.vapix.get_action_rules", return_value=[motion_action_rule]), \
         patch("cctv.reconciler.vapix.remove_action_rule") as mock_rm_rule, \
         patch("cctv.reconciler.vapix.remove_action_configuration") as mock_rm_cfg, \
         patch("cctv.reconciler.vapix.add_action_configuration") as mock_add_cfg, \
         patch("cctv.reconciler.vapix.add_action_rule") as mock_add_rule:
        mock_get.side_effect = [smb_params_response, motion_params_response, storage_params_response, volatile_hostname_response]
        result = reconcile(CAM, camera_config, mock_auth)

    assert "motion_rule" not in result.settings_changed
    mock_rm_rule.assert_not_called()
    mock_rm_cfg.assert_not_called()
    mock_add_cfg.assert_not_called()
    mock_add_rule.assert_not_called()


def test_reconcile_legacy_vmd_app_uses_app_event_topic(
    camera_config, mock_auth, smb_params_response, motion_params_response,
    storage_params_response, volatile_hostname_response,
) -> None:
    """FR35: camera already running the legacy 'VideoMotionDetection' package →
    action rule created against the app's own event topic, not the built-in one."""
    from cctv.vapix import InstalledApplication
    from cctv.reconciler import _LEGACY_VMD_APP_MOTION_TOPIC, _LEGACY_VMD_APP_MOTION_FILTER
    legacy_app = InstalledApplication(name="VideoMotionDetection", nice_name="AXIS Video Motion Detection", status="Running")

    with patch("cctv.reconciler.vapix.get_params") as mock_get, \
         patch("cctv.reconciler.vapix.set_params"), \
         patch("cctv.reconciler.vapix.get_applications", return_value=[legacy_app]), \
         patch("cctv.reconciler.vapix.get_action_configurations", return_value=[]), \
         patch("cctv.reconciler.vapix.get_action_rules", return_value=[]), \
         patch("cctv.reconciler.vapix.add_action_configuration", return_value=11), \
         patch("cctv.reconciler.vapix.add_action_rule") as mock_add_rule:
        mock_get.side_effect = [smb_params_response, motion_params_response, storage_params_response, volatile_hostname_response]
        result = reconcile(CAM, camera_config, mock_auth)

    assert "motion_rule" in result.settings_changed
    mock_add_rule.assert_called_once()
    _, kwargs = mock_add_rule.call_args
    assert kwargs["topic"] == _LEGACY_VMD_APP_MOTION_TOPIC
    assert kwargs["message_filter"] == _LEGACY_VMD_APP_MOTION_FILTER


def test_reconcile_builtin_vmd_app_uses_builtin_topic(
    camera_config, mock_auth, smb_params_response, motion_params_response,
    storage_params_response, volatile_hostname_response,
) -> None:
    """Camera running the built-in 'vmd' package (VMD3/VMD4) → unchanged built-in topic."""
    from cctv.reconciler import _BUILTIN_MOTION_TOPIC

    with patch("cctv.reconciler.vapix.get_params") as mock_get, \
         patch("cctv.reconciler.vapix.set_params"), \
         patch("cctv.reconciler.vapix.get_action_configurations", return_value=[]), \
         patch("cctv.reconciler.vapix.get_action_rules", return_value=[]), \
         patch("cctv.reconciler.vapix.add_action_configuration", return_value=12), \
         patch("cctv.reconciler.vapix.add_action_rule") as mock_add_rule:
        # default_vmd_app_mocks autouse fixture returns name="vmd" (built-in)
        mock_get.side_effect = [smb_params_response, motion_params_response, storage_params_response, volatile_hostname_response]
        result = reconcile(CAM, camera_config, mock_auth)

    assert "motion_rule" in result.settings_changed
    mock_add_rule.assert_called_once()
    _, kwargs = mock_add_rule.call_args
    assert kwargs["topic"] == _BUILTIN_MOTION_TOPIC


def test_reconcile_newly_installed_legacy_app_uses_app_event_topic(
    camera_config, legacy_profile, mock_auth, smb_params_response, motion_params_response,
    storage_params_response, volatile_hostname_response,
) -> None:
    """FR35: app installed THIS run (Story 3.6 path) → rule still uses the app's topic,
    not just when the app was already installed beforehand."""
    from cctv.vapix import InstalledApplication
    from cctv.reconciler import _LEGACY_VMD_APP_MOTION_TOPIC
    legacy_profile.applications["video_motion_detection"] = {"app_package_path": "/opt/eap/AXIS_Video_Motion_Detection_2_2_1.eap"}
    installed_after_upload = InstalledApplication(
        name="VideoMotionDetection", nice_name="AXIS Video Motion Detection", status="Stopped",
    )

    with patch("cctv.reconciler.vapix.get_params") as mock_get, \
         patch("cctv.reconciler.vapix.set_params"), \
         patch("cctv.reconciler.vapix.get_applications", side_effect=[[], [installed_after_upload]]), \
         patch("cctv.reconciler.vapix.upload_application"), \
         patch("cctv.reconciler.vapix.start_application"), \
         patch("cctv.reconciler.vapix.get_action_configurations", return_value=[]), \
         patch("cctv.reconciler.vapix.get_action_rules", return_value=[]), \
         patch("cctv.reconciler.vapix.add_action_configuration", return_value=13), \
         patch("cctv.reconciler.vapix.add_action_rule") as mock_add_rule:
        mock_get.side_effect = [smb_params_response, motion_params_response, storage_params_response, volatile_hostname_response]
        result = reconcile(CAM, camera_config, mock_auth)

    assert "motion_app_installed" in result.settings_changed
    assert "motion_rule" in result.settings_changed
    _, kwargs = mock_add_rule.call_args
    assert kwargs["topic"] == _LEGACY_VMD_APP_MOTION_TOPIC


def test_reconcile_legacy_app_migrates_existing_builtin_topic_rule(
    camera_config, mock_auth, smb_params_response, motion_params_response,
    storage_params_response, volatile_hostname_response,
) -> None:
    """Regression (real-hardware finding, 2026-08-03, cameras 192.168.1.57/.79):
    a pre-existing rule on the built-in topic with already-matching durations must
    NOT be treated as 'already configured' once the camera is running the legacy
    VMD app — matching durations alone isn't enough; the topic itself has to
    match too, or the rule is silently left on the wrong (non-firing) topic
    forever across every future `cctv apply` re-run."""
    from cctv.vapix import InstalledApplication, ActionConfiguration, ActionRule
    from cctv.reconciler import _LEGACY_VMD_APP_MOTION_TOPIC, _BUILTIN_MOTION_TOPIC
    legacy_app = InstalledApplication(name="VideoMotionDetection", nice_name="AXIS Video Motion Detection", status="Running")
    old_cfg = ActionConfiguration(
        config_id=30, name="cctv_motion_record",
        template_token="com.axis.action.unlimited.recording.storage",
        parameters={"storage_id": "NetworkShare", "pre_duration": "5000", "post_duration": "5000", "stream_options": ""},
    )
    old_rule = ActionRule(rule_id=30, name="cctv_motion_record", enabled=True,
                          topic=_BUILTIN_MOTION_TOPIC + "//.", primary_action=30)

    with patch("cctv.reconciler.vapix.get_params") as mock_get, \
         patch("cctv.reconciler.vapix.set_params"), \
         patch("cctv.reconciler.vapix.get_applications", return_value=[legacy_app]), \
         patch("cctv.reconciler.vapix.get_action_configurations", return_value=[old_cfg]), \
         patch("cctv.reconciler.vapix.get_action_rules", return_value=[old_rule]), \
         patch("cctv.reconciler.vapix.remove_action_rule") as mock_rm_rule, \
         patch("cctv.reconciler.vapix.remove_action_configuration") as mock_rm_cfg, \
         patch("cctv.reconciler.vapix.add_action_configuration", return_value=31), \
         patch("cctv.reconciler.vapix.add_action_rule") as mock_add_rule:
        mock_get.side_effect = [smb_params_response, motion_params_response, storage_params_response, volatile_hostname_response]
        result = reconcile(CAM, camera_config, mock_auth)

    assert "motion_rule" in result.settings_changed
    mock_rm_rule.assert_called_once_with(CAM.ip, mock_auth, camera_config.timeout, 30)
    mock_rm_cfg.assert_called_once_with(CAM.ip, mock_auth, camera_config.timeout, 30)
    _, kwargs = mock_add_rule.call_args
    assert kwargs["topic"] == _LEGACY_VMD_APP_MOTION_TOPIC


def test_reconcile_non_networkshare_action_not_counted(
    camera_config, mock_auth, smb_params_response, motion_params_response,
    storage_params_response, volatile_hostname_response, motion_action_rule,
) -> None:
    """Motion rule pointing to SD card (not NetworkShare) must still create a new NetworkShare rule."""
    from cctv.vapix import ActionConfiguration
    sd_config = ActionConfiguration(
        config_id=motion_action_rule.primary_action,
        name="sd_record",
        template_token="com.axis.action.unlimited.recording.storage",
        parameters={"storage_id": "SD_DISK"},
    )
    with patch("cctv.reconciler.vapix.get_params") as mock_get, \
         patch("cctv.reconciler.vapix.set_params"), \
         patch("cctv.reconciler.vapix.get_action_configurations", return_value=[sd_config]), \
         patch("cctv.reconciler.vapix.get_action_rules", return_value=[motion_action_rule]), \
         patch("cctv.reconciler.vapix.add_action_configuration", return_value=10), \
         patch("cctv.reconciler.vapix.add_action_rule") as mock_add_rule:
        mock_get.side_effect = [smb_params_response, motion_params_response, storage_params_response, volatile_hostname_response]
        result = reconcile(CAM, camera_config, mock_auth)

    assert "motion_rule" in result.settings_changed
    mock_add_rule.assert_called_once()


# ---------------------------------------------------------------------------
# Profile matching and the firmware precondition
# ---------------------------------------------------------------------------


def test_reconcile_unmatched_model_raises_before_any_read(camera_config, mock_auth) -> None:
    """A camera whose model matches no profile is a failure for that run, not a
    silent skip — and it fails before any camera state is read or written."""
    unknown = DiscoveredCamera(ip="192.168.1.199", model="AXIS Q6135-LE PTZ")

    with patch("cctv.reconciler.vapix.get_params") as mock_get, \
         patch("cctv.reconciler.vapix.set_params") as mock_set:
        with pytest.raises(VapixError, match="No profile in cameras.yaml matches"):
            reconcile(unknown, camera_config, mock_auth)

    mock_get.assert_not_called()
    mock_set.assert_not_called()


def test_reconcile_firmware_mismatch_raises_before_any_write(
    camera_config, legacy_profile, mock_auth
) -> None:
    """target_firmware is a precondition: a mismatch fails the camera before any
    setting is touched, so it is never left partially converged. cctv never upgrades."""
    legacy_profile.target_firmware = "5.51.7.4"

    with patch("cctv.reconciler.vapix.get_params", return_value={_FIRMWARE_VERSION: "5.40.9.2"}), \
         patch("cctv.reconciler.vapix.set_params") as mock_set:
        with pytest.raises(VapixError, match="Firmware mismatch") as exc_info:
            reconcile(CAM, camera_config, mock_auth)

    assert "does not" in str(exc_info.value)  # states cctv won't auto-upgrade
    mock_set.assert_not_called()


def test_reconcile_firmware_match_proceeds(
    camera_config, legacy_profile, mock_auth, smb_params_response, motion_params_response,
    storage_params_response, volatile_hostname_response,
) -> None:
    """Firmware matches the profile's precondition → reconciliation continues normally."""
    legacy_profile.target_firmware = "5.51.7.4"

    with patch("cctv.reconciler.vapix.get_params") as mock_get, \
         patch("cctv.reconciler.vapix.set_params") as mock_set:
        mock_get.side_effect = [
            {_FIRMWARE_VERSION: "5.51.7.4"},
            smb_params_response, motion_params_response,
            storage_params_response, volatile_hostname_response,
        ]
        result = reconcile(CAM, camera_config, mock_auth)

    assert result.status == CameraStatus.NO_CHANGE
    mock_set.assert_not_called()


def test_reconcile_firmware_not_read_when_precondition_absent(
    camera_config, mock_auth, smb_params_response, motion_params_response,
    storage_params_response, volatile_hostname_response,
) -> None:
    """No target_firmware in the profile → the version param is never read at all."""
    with patch("cctv.reconciler.vapix.get_params") as mock_get, \
         patch("cctv.reconciler.vapix.set_params"):
        mock_get.side_effect = [smb_params_response, motion_params_response, storage_params_response, volatile_hostname_response]
        reconcile(CAM, camera_config, mock_auth)

    for c in mock_get.call_args_list:
        assert c.args[1] != _FIRMWARE_VERSION


# ---------------------------------------------------------------------------
# Fleet-wide NTP fallback servers
# ---------------------------------------------------------------------------


def test_reconcile_ntp_fallback_set_when_differs(
    camera_config, mock_auth, smb_params_response, motion_params_response,
    storage_params_response, volatile_hostname_response,
) -> None:
    """Configured fallback servers differ from the camera's → full-replace write."""
    camera_config.ntp_fallback_servers = ["pool.ntp.org", "ntp1.vniiftri.ru"]

    with patch("cctv.reconciler.vapix.get_params") as mock_get, \
         patch("cctv.reconciler.vapix.set_params"), \
         patch("cctv.reconciler.vapix.get_ntp_fallback_servers", return_value=["pool.ntp.org"]), \
         patch("cctv.reconciler.vapix.set_ntp_fallback_servers") as mock_set_ntp:
        mock_get.side_effect = [smb_params_response, motion_params_response, storage_params_response, volatile_hostname_response]
        result = reconcile(CAM, camera_config, mock_auth)

    assert "ntp_fallback" in result.settings_changed
    mock_set_ntp.assert_called_once_with(
        CAM.ip, mock_auth, camera_config.timeout, ["pool.ntp.org", "ntp1.vniiftri.ru"],
    )


def test_reconcile_ntp_fallback_no_change_when_matches(
    camera_config, mock_auth, smb_params_response, motion_params_response,
    storage_params_response, volatile_hostname_response,
) -> None:
    """Camera already lists exactly the configured servers → no write."""
    camera_config.ntp_fallback_servers = ["pool.ntp.org", "ntp1.vniiftri.ru"]

    with patch("cctv.reconciler.vapix.get_params") as mock_get, \
         patch("cctv.reconciler.vapix.set_params"), \
         patch("cctv.reconciler.vapix.get_ntp_fallback_servers", return_value=["pool.ntp.org", "ntp1.vniiftri.ru"]), \
         patch("cctv.reconciler.vapix.set_ntp_fallback_servers") as mock_set_ntp:
        mock_get.side_effect = [smb_params_response, motion_params_response, storage_params_response, volatile_hostname_response]
        result = reconcile(CAM, camera_config, mock_auth)

    assert "ntp_fallback" not in result.settings_changed
    mock_set_ntp.assert_not_called()


def test_reconcile_ntp_fallback_skipped_when_not_configured(
    camera_config, mock_auth, smb_params_response, motion_params_response,
    storage_params_response, volatile_hostname_response,
) -> None:
    """Empty ntp_fallback_servers → the NTP endpoint is never even read."""
    with patch("cctv.reconciler.vapix.get_params") as mock_get, \
         patch("cctv.reconciler.vapix.set_params"), \
         patch("cctv.reconciler.vapix.get_ntp_fallback_servers") as mock_get_ntp:
        mock_get.side_effect = [smb_params_response, motion_params_response, storage_params_response, volatile_hostname_response]
        reconcile(CAM, camera_config, mock_auth)

    mock_get_ntp.assert_not_called()


# ---------------------------------------------------------------------------
# sd_s3sync backend (AXIS OS 12.x — SD card recording synced to S3 by an ACAP)
# ---------------------------------------------------------------------------


@pytest.fixture
def sd_backend_mocks(vmd_app_running, sds3sync_app_running, sd_action_config, sd_action_rule):
    """Healthy steady state for an M3085-V: VMD4 running and full-frame, the
    sd_to_s3_sync ACAP installed/configured/running, SD-record rule in place.
    Tests override individual patches to exercise the divergent paths."""
    from cctv.vapix import Vmd4Profile
    full_frame_data = {
        "configurationStatus": 0,
        "profiles": [{
            "camera": 1, "uid": 1, "name": "Profile 1",
            "filters": [
                {"active": True, "type": "sizePercentage", "data": [5, 5]},
                {"active": True, "type": "timeShortLivedLimit", "data": 1},
                {"active": True, "type": "distanceSwayingObject", "data": 5},
            ],
            "triggers": [{"type": "includeArea", "data": [[-1.0, -1.0], [-1.0, 1.0], [1.0, 1.0], [1.0, -1.0]]}],
        }],
        "cameras": [{"id": 1, "rotation": 0, "active": True}],
    }
    with patch("cctv.reconciler.vapix.get_applications", return_value=[vmd_app_running, sds3sync_app_running]), \
         patch("cctv.reconciler.vapix.get_vmd4_configuration", return_value=full_frame_data), \
         patch("cctv.reconciler.vapix.set_vmd4_configuration"), \
         patch("cctv.reconciler.vapix.get_vmd4_profiles", return_value=[Vmd4Profile(uid=1, name="Profile 1", camera=1)]), \
         patch("cctv.reconciler.vapix.get_action_configurations", return_value=[sd_action_config]), \
         patch("cctv.reconciler.vapix.get_action_rules", return_value=[sd_action_rule]), \
         patch("cctv.reconciler.vapix.add_action_configuration"), \
         patch("cctv.reconciler.vapix.add_action_rule"), \
         patch("cctv.reconciler.vapix.remove_action_rule"), \
         patch("cctv.reconciler.vapix.remove_action_configuration"), \
         patch("cctv.reconciler.vapix.upload_application"), \
         patch("cctv.reconciler.vapix.start_application"), \
         patch("cctv.reconciler.vapix.stop_application"):
        yield


def test_reconcile_sd_backend_all_match_returns_no_change(
    camera_config, mock_auth, sd_backend_mocks, sds3sync_params_response,
    sd_storage_params_response, volatile_hostname_response,
) -> None:
    """M3085-V already fully converged → NO_CHANGE, no writes of any kind."""
    with patch("cctv.reconciler.vapix.get_params") as mock_get, \
         patch("cctv.reconciler.vapix.set_params") as mock_set:
        mock_get.side_effect = [sds3sync_params_response, sd_storage_params_response, volatile_hostname_response]
        result = reconcile(SD_CAM, camera_config, mock_auth)

    assert result.status == CameraStatus.NO_CHANGE
    assert result.settings_changed == []
    mock_set.assert_not_called()


def test_reconcile_sd_backend_selected_by_model(
    camera_config, mock_auth, sd_backend_mocks, sds3sync_params_response,
    sd_storage_params_response, volatile_hostname_response,
) -> None:
    """An M3085-V routes to the sd_s3sync profile, so the SMB param group —
    which errors outright on this firmware — is never touched."""
    from cctv.reconciler import _SMB_GROUP, _MOTION_GROUP
    with patch("cctv.reconciler.vapix.get_params") as mock_get, \
         patch("cctv.reconciler.vapix.set_params"):
        mock_get.side_effect = [sds3sync_params_response, sd_storage_params_response, volatile_hostname_response]
        reconcile(SD_CAM, camera_config, mock_auth)

    read_groups = [c.args[1] for c in mock_get.call_args_list]
    assert _SMB_GROUP not in read_groups
    assert _MOTION_GROUP not in read_groups


def test_reconcile_sd_backend_uses_s0_retention_group(
    camera_config, mock_auth, sd_backend_mocks, sds3sync_params_response,
    volatile_hostname_response,
) -> None:
    """Retention applies to S0 (SD card) on this backend, not S1 (NetworkShare)."""
    stale_retention = {_STORAGE_RETENTION_S0: "7"}

    with patch("cctv.reconciler.vapix.get_params") as mock_get, \
         patch("cctv.reconciler.vapix.set_params") as mock_set:
        mock_get.side_effect = [sds3sync_params_response, stale_retention, volatile_hostname_response]
        result = reconcile(SD_CAM, camera_config, mock_auth)

    assert "retention" in result.settings_changed
    mock_set.assert_called_once_with(
        SD_CAM.ip, {_STORAGE_RETENTION_S0: "33"}, mock_auth, camera_config.timeout,
    )


def test_reconcile_sd_backend_starts_stopped_vmd(
    camera_config, mock_auth, sd_backend_mocks, sds3sync_params_response,
    sd_storage_params_response, volatile_hostname_response, sds3sync_app_running,
) -> None:
    """VMD4 ships Stopped on factory-default units → started, never installed
    (it is bundled with the firmware on this model)."""
    from cctv.vapix import InstalledApplication
    stopped_vmd = InstalledApplication(name="vmd", nice_name="AXIS Video Motion Detection", status="Stopped", version="4.5.70")

    with patch("cctv.reconciler.vapix.get_params") as mock_get, \
         patch("cctv.reconciler.vapix.set_params"), \
         patch("cctv.reconciler.vapix.get_applications", return_value=[stopped_vmd, sds3sync_app_running]), \
         patch("cctv.reconciler.vapix.upload_application") as mock_upload, \
         patch("cctv.reconciler.vapix.start_application") as mock_start:
        mock_get.side_effect = [sds3sync_params_response, sd_storage_params_response, volatile_hostname_response]
        result = reconcile(SD_CAM, camera_config, mock_auth)

    assert "motion_app_started" in result.settings_changed
    mock_upload.assert_not_called()
    mock_start.assert_called_once_with(SD_CAM.ip, mock_auth, camera_config.timeout, "vmd")


def test_reconcile_sd_backend_missing_vmd_raises(
    camera_config, mock_auth, sd_backend_mocks, sds3sync_app_running,
) -> None:
    """VMD4 absent on a model that should bundle it → clear failure, not a silent install."""
    with patch("cctv.reconciler.vapix.get_params"), \
         patch("cctv.reconciler.vapix.get_applications", return_value=[sds3sync_app_running]), \
         patch("cctv.reconciler.vapix.upload_application") as mock_upload:
        with pytest.raises(VapixError, match="expected bundled/pre-installed"):
            reconcile(SD_CAM, camera_config, mock_auth)

    mock_upload.assert_not_called()


def test_reconcile_sd_backend_updates_vmd4_filters(
    camera_config, s3_profile, mock_auth, sd_backend_mocks, sds3sync_params_response,
    sd_storage_params_response, volatile_hostname_response,
) -> None:
    """Filter values differing from the profile are converged in place; filter
    types the camera does not already have are not invented."""
    s3_profile.motion_detection["size_percentage"] = [10, 10]
    drifted = {
        "configurationStatus": 0,
        "profiles": [{
            "camera": 1, "uid": 1, "name": "Profile 1",
            "filters": [
                {"active": True, "type": "sizePercentage", "data": [5, 5]},
                {"active": True, "type": "timeShortLivedLimit", "data": 1},
            ],
            "triggers": [{"type": "includeArea", "data": [[-1.0, -1.0], [-1.0, 1.0], [1.0, 1.0], [1.0, -1.0]]}],
        }],
        "cameras": [{"id": 1, "rotation": 0, "active": True}],
    }

    with patch("cctv.reconciler.vapix.get_params") as mock_get, \
         patch("cctv.reconciler.vapix.set_params"), \
         patch("cctv.reconciler.vapix.get_vmd4_configuration", return_value=drifted), \
         patch("cctv.reconciler.vapix.set_vmd4_configuration") as mock_set_vmd4:
        mock_get.side_effect = [sds3sync_params_response, sd_storage_params_response, volatile_hostname_response]
        result = reconcile(SD_CAM, camera_config, mock_auth)

    assert "motion_filters" in result.settings_changed
    posted = mock_set_vmd4.call_args[0][3]
    filters = posted["profiles"][0]["filters"]
    assert {"active": True, "type": "sizePercentage", "data": [10, 10]} in filters
    assert [f["type"] for f in filters] == ["sizePercentage", "timeShortLivedLimit"]


def test_reconcile_sd_backend_installs_missing_acap(
    camera_config, mock_auth, sd_backend_mocks, vmd_app_running, sds3sync_app_running,
    sds3sync_params_response, sd_storage_params_response, volatile_hostname_response,
) -> None:
    """sd_to_s3_sync absent → uploaded from the configured .eap, then re-listed."""
    with patch("cctv.reconciler.vapix.get_params") as mock_get, \
         patch("cctv.reconciler.vapix.set_params"), \
         patch("cctv.reconciler.vapix.get_applications",
               side_effect=[[vmd_app_running], [vmd_app_running], [vmd_app_running, sds3sync_app_running],
                            [vmd_app_running, sds3sync_app_running]]), \
         patch("cctv.reconciler.vapix.upload_application") as mock_upload, \
         patch("cctv.reconciler.vapix.start_application"):
        mock_get.side_effect = [sds3sync_params_response, sd_storage_params_response, volatile_hostname_response]
        result = reconcile(SD_CAM, camera_config, mock_auth)

    assert "sd_to_s3_sync_installed" in result.settings_changed
    mock_upload.assert_called_once_with(
        SD_CAM.ip, mock_auth, camera_config.timeout,
        "/opt/eap/signed_SD_to_S3_Sync_0_9_5_aarch64.eap",
    )


def test_reconcile_sd_backend_missing_acap_without_package_path_raises(
    camera_config, s3_profile, mock_auth, sd_backend_mocks, vmd_app_running,
) -> None:
    """ACAP absent and no app_package_path to install it from → clear failure."""
    s3_profile.applications["sd_to_s3_sync"] = {}

    with patch("cctv.reconciler.vapix.get_params"), \
         patch("cctv.reconciler.vapix.get_applications", return_value=[vmd_app_running]), \
         patch("cctv.reconciler.vapix.upload_application") as mock_upload:
        with pytest.raises(VapixError, match="app_package_path"):
            reconcile(SD_CAM, camera_config, mock_auth)

    mock_upload.assert_not_called()


def test_reconcile_sd_backend_writes_only_drifted_acap_params(
    camera_config, mock_auth, sd_backend_mocks, sds3sync_params_response,
    sd_storage_params_response, volatile_hostname_response,
) -> None:
    """Only the differing root.Sds3sync params are written, not the whole group."""
    drifted = {**sds3sync_params_response, "root.Sds3sync.S3Bucket": "stale-bucket"}

    with patch("cctv.reconciler.vapix.get_params") as mock_get, \
         patch("cctv.reconciler.vapix.set_params") as mock_set:
        mock_get.side_effect = [drifted, sd_storage_params_response, volatile_hostname_response]
        result = reconcile(SD_CAM, camera_config, mock_auth)

    assert "sd_to_s3_sync_config" in result.settings_changed
    mock_set.assert_called_once_with(
        SD_CAM.ip, {"root.Sds3sync.S3Bucket": "my-cctv-bucket"}, mock_auth, camera_config.timeout,
    )


def test_reconcile_sd_backend_never_writes_acap_prefix(
    camera_config, mock_auth, sd_backend_mocks, sd_storage_params_response,
    volatile_hostname_response,
) -> None:
    """Prefix is left to the ACAP to derive from the camera's own hostname, so
    every camera gets its own bucket namespace with no per-camera config."""
    with patch("cctv.reconciler.vapix.get_params") as mock_get, \
         patch("cctv.reconciler.vapix.set_params") as mock_set:
        mock_get.side_effect = [{}, sd_storage_params_response, volatile_hostname_response]
        reconcile(SD_CAM, camera_config, mock_auth)

    written = mock_set.call_args_list[0].args[1]
    assert "root.Sds3sync.Prefix" not in written


def test_reconcile_sd_backend_restarts_acap_after_config_change(
    camera_config, mock_auth, sd_backend_mocks, sd_storage_params_response,
    volatile_hostname_response,
) -> None:
    """Real-hardware finding: the ACAP reads its config only at startup, so a
    running app whose config just changed must be stopped and started again."""
    with patch("cctv.reconciler.vapix.get_params") as mock_get, \
         patch("cctv.reconciler.vapix.set_params"), \
         patch("cctv.reconciler.vapix.stop_application") as mock_stop, \
         patch("cctv.reconciler.vapix.start_application") as mock_start:
        mock_get.side_effect = [{}, sd_storage_params_response, volatile_hostname_response]
        result = reconcile(SD_CAM, camera_config, mock_auth)

    assert "sd_to_s3_sync_restarted" in result.settings_changed
    mock_stop.assert_called_once_with(SD_CAM.ip, mock_auth, camera_config.timeout, "sds3sync")
    mock_start.assert_called_once_with(SD_CAM.ip, mock_auth, camera_config.timeout, "sds3sync")


def test_reconcile_sd_backend_no_restart_when_config_unchanged(
    camera_config, mock_auth, sd_backend_mocks, sds3sync_params_response,
    sd_storage_params_response, volatile_hostname_response,
) -> None:
    """A running, already-correctly-configured ACAP is left alone — no needless
    restart that would interrupt an in-flight upload on every reconcile."""
    with patch("cctv.reconciler.vapix.get_params") as mock_get, \
         patch("cctv.reconciler.vapix.set_params"), \
         patch("cctv.reconciler.vapix.stop_application") as mock_stop, \
         patch("cctv.reconciler.vapix.start_application") as mock_start:
        mock_get.side_effect = [sds3sync_params_response, sd_storage_params_response, volatile_hostname_response]
        result = reconcile(SD_CAM, camera_config, mock_auth)

    assert "sd_to_s3_sync_restarted" not in result.settings_changed
    mock_stop.assert_not_called()
    mock_start.assert_not_called()


def test_reconcile_sd_backend_starts_stopped_acap_without_stopping_first(
    camera_config, mock_auth, sd_backend_mocks, vmd_app_running,
    sds3sync_params_response, sd_storage_params_response, volatile_hostname_response,
) -> None:
    """A stopped, already-configured ACAP is simply started."""
    from cctv.vapix import InstalledApplication
    stopped_acap = InstalledApplication(name="sds3sync", nice_name="SD to S3 Sync", status="Stopped", version="0.9.5")

    with patch("cctv.reconciler.vapix.get_params") as mock_get, \
         patch("cctv.reconciler.vapix.set_params"), \
         patch("cctv.reconciler.vapix.get_applications", return_value=[vmd_app_running, stopped_acap]), \
         patch("cctv.reconciler.vapix.stop_application") as mock_stop, \
         patch("cctv.reconciler.vapix.start_application") as mock_start:
        mock_get.side_effect = [sds3sync_params_response, sd_storage_params_response, volatile_hostname_response]
        result = reconcile(SD_CAM, camera_config, mock_auth)

    assert "sd_to_s3_sync_started" in result.settings_changed
    mock_stop.assert_not_called()
    mock_start.assert_called_once_with(SD_CAM.ip, mock_auth, camera_config.timeout, "sds3sync")


def test_reconcile_sd_backend_creates_sd_record_rule(
    camera_config, mock_auth, sd_backend_mocks, sds3sync_params_response,
    sd_storage_params_response, volatile_hostname_response,
) -> None:
    """No rule present → created against the VMD4 profile topic, recording to
    SD_DISK with the profile's own pre/post durations."""
    with patch("cctv.reconciler.vapix.get_params") as mock_get, \
         patch("cctv.reconciler.vapix.set_params"), \
         patch("cctv.reconciler.vapix.get_action_configurations", return_value=[]), \
         patch("cctv.reconciler.vapix.get_action_rules", return_value=[]), \
         patch("cctv.reconciler.vapix.add_action_configuration", return_value=21) as mock_add_cfg, \
         patch("cctv.reconciler.vapix.add_action_rule") as mock_add_rule:
        mock_get.side_effect = [sds3sync_params_response, sd_storage_params_response, volatile_hostname_response]
        result = reconcile(SD_CAM, camera_config, mock_auth)

    assert "motion_rule" in result.settings_changed
    cfg_kwargs = mock_add_cfg.call_args.kwargs
    assert cfg_kwargs["name"] == "cctv_motion_sd_record"
    assert cfg_kwargs["parameters"]["storage_id"] == "SD_DISK"
    assert cfg_kwargs["parameters"]["pre_duration"] == "5000"
    assert cfg_kwargs["parameters"]["post_duration"] == "2000"

    rule_kwargs = mock_add_rule.call_args.kwargs
    assert rule_kwargs["topic"] == "tnsaxis:CameraApplicationPlatform/VMD/Camera1Profile1"
    assert rule_kwargs["primary_action"] == 21


def test_reconcile_sd_backend_rule_uses_concrete_profile_uid(
    camera_config, mock_auth, sd_backend_mocks, sds3sync_params_response,
    sd_storage_params_response, volatile_hostname_response,
) -> None:
    """The rule targets the camera's actual VMD4 profile uid, not a wildcard —
    AddActionRule rejects the ProfileANY wildcard on creation."""
    from cctv.vapix import Vmd4Profile

    with patch("cctv.reconciler.vapix.get_params") as mock_get, \
         patch("cctv.reconciler.vapix.set_params"), \
         patch("cctv.reconciler.vapix.get_vmd4_profiles", return_value=[Vmd4Profile(uid=3, name="Profile 3", camera=1)]), \
         patch("cctv.reconciler.vapix.get_action_configurations", return_value=[]), \
         patch("cctv.reconciler.vapix.get_action_rules", return_value=[]), \
         patch("cctv.reconciler.vapix.add_action_configuration", return_value=22), \
         patch("cctv.reconciler.vapix.add_action_rule") as mock_add_rule:
        mock_get.side_effect = [sds3sync_params_response, sd_storage_params_response, volatile_hostname_response]
        reconcile(SD_CAM, camera_config, mock_auth)

    topic = mock_add_rule.call_args.kwargs["topic"]
    assert topic == "tnsaxis:CameraApplicationPlatform/VMD/Camera1Profile3"
    assert "ANY" not in topic


def test_reconcile_sd_backend_motion_disabled_skips_motion_but_keeps_sync(
    camera_config, s3_profile, mock_auth, sd_backend_mocks, sds3sync_params_response,
    sd_storage_params_response, volatile_hostname_response,
) -> None:
    """motion_detection.enabled=false → no VMD4 or action-rule work, but the
    storage backend itself is still converged."""
    s3_profile.motion_detection["enabled"] = False

    with patch("cctv.reconciler.vapix.get_params") as mock_get, \
         patch("cctv.reconciler.vapix.set_params"), \
         patch("cctv.reconciler.vapix.get_vmd4_configuration") as mock_get_vmd4, \
         patch("cctv.reconciler.vapix.get_action_rules") as mock_get_rules:
        mock_get.side_effect = [sds3sync_params_response, sd_storage_params_response, volatile_hostname_response]
        result = reconcile(SD_CAM, camera_config, mock_auth)

    assert result.status == CameraStatus.NO_CHANGE
    mock_get_vmd4.assert_not_called()
    mock_get_rules.assert_not_called()


def test_reconcile_sd_backend_s3_secret_not_in_vapix_error(
    camera_config, mock_auth, sd_backend_mocks, sd_storage_params_response,
    volatile_hostname_response,
) -> None:
    """NFR7: the S3 secret key must not leak into any VapixError message."""
    with patch("cctv.reconciler.vapix.get_params") as mock_get, \
         patch("cctv.reconciler.vapix.set_params", side_effect=VapixError("SET params on 192.168.0.24 failed: 401 Unauthorized")):
        mock_get.side_effect = [{}, sd_storage_params_response, volatile_hostname_response]
        with pytest.raises(VapixError) as exc_info:
            reconcile(SD_CAM, camera_config, mock_auth)

    assert camera_config.profiles[1].storage.sd_s3sync.secret_key not in str(exc_info.value)


# ---------------------------------------------------------------------------
# Network share index resolution — the Nx slot is internal parhand bookkeeping
# and is not always N0 (real hardware: 192.168.1.60 serves its only share from
# N1 while 192.168.1.79 serves the identical share from N0).
# ---------------------------------------------------------------------------

def test_find_network_share_index_defaults_to_n0_when_unconfigured() -> None:
    """No share configured at all → N0, the slot a camera gives its first share."""
    assert find_network_share_index({}) == "N0"


def test_find_network_share_index_finds_sole_share_at_n1() -> None:
    """Share living at N1 is found — reading a hardcoded N0 here yields nothing."""
    smb = {
        "root.NetworkShare.N1.Address": "192.168.1.100",
        "root.NetworkShare.N1.Share": "cctv",
        "root.NetworkShare.N1.Username": "cctv",
    }
    assert find_network_share_index(smb) == "N1"


def test_find_network_share_index_prefers_slot_matching_desired() -> None:
    """With two shares configured, the one matching desired host/share wins over the lowest."""
    smb = {
        "root.NetworkShare.N0.Address": "192.168.1.200",
        "root.NetworkShare.N0.Share": "other",
        "root.NetworkShare.N2.Address": "192.168.1.100",
        "root.NetworkShare.N2.Share": "cctv",
    }
    assert find_network_share_index(smb, "192.168.1.100", "cctv") == "N2"


def test_find_network_share_index_falls_back_to_lowest_when_no_match() -> None:
    """Nothing matches desired → lowest configured slot, ordered numerically not lexically."""
    smb = {
        "root.NetworkShare.N10.Address": "192.168.1.200",
        "root.NetworkShare.N2.Address": "192.168.1.201",
    }
    assert find_network_share_index(smb, "10.0.0.1", "nope") == "N2"


def test_smb_param_keys_builds_keys_for_given_index() -> None:
    assert smb_param_keys("N1") == (
        "root.NetworkShare.N1.Address",
        "root.NetworkShare.N1.Share",
        "root.NetworkShare.N1.Username",
        "root.NetworkShare.N1.Password",
    )


def test_reconcile_smb_writes_to_n1_not_n0(
    camera_config, mock_auth, motion_params_response,
    storage_params_response, volatile_hostname_response,
) -> None:
    """Camera whose share sits at N1 with a stale host → correction written to N1.

    Regression: previously the reconciler read and wrote a hardcoded N0, so on such
    a camera it saw no share at all and would have written a duplicate at N0.
    """
    smb_at_n1 = {
        "root.NetworkShare.N1.Address": "10.0.0.99",   # stale — differs from config
        "root.NetworkShare.N1.Share": "/mnt/cctv",
        "root.NetworkShare.N1.Username": "smbuser",
        "root.NetworkShare.N1.Password": "smbpass",
    }

    with patch("cctv.reconciler.vapix.get_params") as mock_get, \
         patch("cctv.reconciler.vapix.set_params") as mock_set:
        mock_get.side_effect = [smb_at_n1, motion_params_response, storage_params_response, volatile_hostname_response]
        result = reconcile(CAM, camera_config, mock_auth)

    assert result.status == CameraStatus.APPLIED
    assert "smb_ip" in result.settings_changed
    assert "smb_creds" not in result.settings_changed  # creds already correct at N1
    mock_set.assert_called_once_with(
        CAM.ip,
        {"root.NetworkShare.N1.Address": camera_config.profiles[0].storage.smb.ip},
        mock_auth,
        camera_config.timeout,
    )
