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
    _MOTION_SENSITIVITY,
    _STORAGE_RETENTION,
    _TIME_TIMEZONE,
    _NETWORK_HOSTNAME,
    _NETWORK_VOLATILE_HOSTNAME,
)
from cctv.scanner import DiscoveredCamera
from cctv.vapix import VapixError

CAM = DiscoveredCamera(ip="192.168.1.101", model="AXIS P3245-V")


@pytest.fixture(autouse=True)
def default_soap_mocks(motion_action_config, motion_action_rule):
    """Default: camera already has a motion rule. Tests that exercise SOAP creation override these."""
    with patch("cctv.reconciler.vapix.get_action_configurations", return_value=[motion_action_config]), \
         patch("cctv.reconciler.vapix.get_action_rules", return_value=[motion_action_rule]), \
         patch("cctv.reconciler.vapix.add_action_configuration"), \
         patch("cctv.reconciler.vapix.add_action_rule"):
        yield


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
        {_SMB_HOST: camera_config.smb_ip},
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
            _SMB_SHARE: camera_config.smb_share,
            _SMB_USER: camera_config.smb_username,
            _SMB_PASS: camera_config.smb_password,
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
        CAM.ip, {_SMB_HOST: camera_config.smb_ip}, mock_auth, camera_config.timeout
    )
    mock_set.assert_any_call(
        CAM.ip,
        {
            _SMB_SHARE: camera_config.smb_share,
            _SMB_USER: camera_config.smb_username,
            _SMB_PASS: camera_config.smb_password,
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
    assert camera_config.smb_password not in str(exc_info.value)


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
    camera_config, mock_auth, smb_params_response, motion_params_response,
    storage_params_response, volatile_hostname_response,
) -> None:
    """D3: config.motion_enabled is never written via param.cgi regardless of camera state."""
    camera_config.motion_enabled = False
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
    camera_config, mock_auth, smb_params_response, motion_params_response,
    storage_params_response, volatile_hostname_response,
) -> None:
    """Float motion_sensitivity (e.g. 90.0) must compare as '90', not '90.0'."""
    camera_config.motion_sensitivity = 90.0
    with patch("cctv.reconciler.vapix.get_params") as mock_get, \
         patch("cctv.reconciler.vapix.set_params") as mock_set:
        mock_get.side_effect = [smb_params_response, motion_params_response, storage_params_response, volatile_hostname_response]
        result = reconcile(CAM, camera_config, mock_auth)

    assert result.status == CameraStatus.NO_CHANGE
    assert "motion" not in result.settings_changed
    mock_set.assert_not_called()


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
    storage_params_response = {**storage_params_response, _STORAGE_RETENTION: "7"}  # camera has 7, config=33

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
        {_STORAGE_RETENTION: "33"},
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
    storage_params_response = {**storage_params_response, _STORAGE_RETENTION: "90"}

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
    camera_config, mock_auth, smb_params_response, motion_params_response,
    storage_params_response, volatile_hostname_response,
) -> None:
    """motion_enabled=False → no SOAP calls at all for action rules."""
    camera_config.motion_enabled = False
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
    camera_config, mock_auth, smb_params_response, motion_params_response,
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
    camera_config.motion_pre_trigger_time = 10
    camera_config.motion_post_trigger_time = 10

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
