from __future__ import annotations

from unittest.mock import patch

from cctv.status import collect_status, collect_all, CameraStatusResult
from cctv.scanner import DiscoveredCamera
from cctv.vapix import VapixError

CAM1 = DiscoveredCamera(ip="192.168.1.101", model="AXIS P3245-V")
CAM2 = DiscoveredCamera(ip="192.168.1.102", model="AXIS P3245-V")

# Every VAPIX call that mutates camera state — status.py must NEVER call any of these.
_WRITE_PATCH_TARGETS = [
    "cctv.vapix.set_params",
    "cctv.vapix.add_action_configuration",
    "cctv.vapix.add_action_rule",
    "cctv.vapix.remove_action_rule",
    "cctv.vapix.remove_action_configuration",
    "cctv.vapix.upload_application",
    "cctv.vapix.start_application",
    "cctv.vapix.add_motion_window",
]


def test_collect_status_full_camera(
    camera_config, mock_auth, smb_params_response, motion_params_response,
    storage_params_response, time_params_response, vmd_app_running,
    motion_action_config, motion_action_rule,
) -> None:
    """Every field is populated from the corresponding VAPIX GET call."""
    with patch("cctv.status.vapix.get_applications", return_value=[vmd_app_running]), \
         patch("cctv.status.vapix.get_action_configurations", return_value=[motion_action_config]), \
         patch("cctv.status.vapix.get_action_rules", return_value=[motion_action_rule]), \
         patch("cctv.status.vapix.get_params") as mock_get:
        mock_get.side_effect = [motion_params_response, smb_params_response, storage_params_response, time_params_response]
        result = collect_status(CAM1, camera_config, mock_auth)

    assert result.ip == CAM1.ip
    assert result.model == CAM1.model
    assert result.error is None
    assert result.motion_app_name == "vmd"
    assert result.motion_app_nice_name == "AXIS Video Motion Detection"
    assert result.motion_app_status == "Running"
    assert result.motion_app_version == "4.3-1"
    assert result.motion_enabled is True
    assert result.motion_window_present is True
    assert result.motion_window_detail == "full-frame window"
    assert result.motion_sensitivity == "90"
    assert len(result.action_rules) == 1
    rule = result.action_rules[0]
    assert rule.name == "cctv_motion_record"
    assert rule.enabled is True
    assert rule.target_template == "com.axis.action.unlimited.recording.storage"
    assert rule.pre_duration_ms == "5000"
    assert rule.post_duration_ms == "5000"
    assert result.smb_ip == "192.168.1.10"
    assert result.smb_share == "/mnt/cctv"
    assert result.smb_username == "smbuser"
    assert result.timezone == "UTC0"
    assert result.retention_days == "33"


def test_collect_status_never_includes_passwords(
    camera_config, mock_auth, smb_params_response, motion_params_response,
    storage_params_response, time_params_response, vmd_app_running,
) -> None:
    """NFR7: no password field anywhere on CameraStatusResult, and the field values never contain the configured passwords."""
    with patch("cctv.status.vapix.get_applications", return_value=[vmd_app_running]), \
         patch("cctv.status.vapix.get_action_configurations", return_value=[]), \
         patch("cctv.status.vapix.get_action_rules", return_value=[]), \
         patch("cctv.status.vapix.get_params") as mock_get:
        mock_get.side_effect = [motion_params_response, smb_params_response, storage_params_response, time_params_response]
        result = collect_status(CAM1, camera_config, mock_auth)

    assert not hasattr(result, "smb_password")
    assert not hasattr(result, "password")
    for value in vars(result).values():
        assert camera_config.smb_password not in str(value)
        assert camera_config.password not in str(value)


def test_collect_status_motion_source_legacy_app(
    camera_config, mock_auth, smb_params_response, motion_params_response,
    storage_params_response, time_params_response,
) -> None:
    """FR35/Story 3.7: installed app named 'VideoMotionDetection' (legacy 2.2.1 .eap) → motion_source labels it as such."""
    from cctv.vapix import InstalledApplication
    legacy_app = InstalledApplication(name="VideoMotionDetection", nice_name="AXIS Video Motion Detection", status="Idle")
    with patch("cctv.status.vapix.get_applications", return_value=[legacy_app]), \
         patch("cctv.status.vapix.get_action_configurations", return_value=[]), \
         patch("cctv.status.vapix.get_action_rules", return_value=[]), \
         patch("cctv.status.vapix.get_vmd_app_config", return_value=[]), \
         patch("cctv.status.vapix.get_params") as mock_get:
        mock_get.side_effect = [motion_params_response, smb_params_response, storage_params_response, time_params_response]
        result = collect_status(CAM1, camera_config, mock_auth)

    assert result.motion_source == "legacy app (.eap)"


def test_collect_status_motion_source_built_in(
    camera_config, mock_auth, smb_params_response, motion_params_response,
    storage_params_response, time_params_response, vmd_app_running,
) -> None:
    """Installed app named 'vmd' (built-in VMD3/VMD4) → motion_source is 'built-in'."""
    with patch("cctv.status.vapix.get_applications", return_value=[vmd_app_running]), \
         patch("cctv.status.vapix.get_action_configurations", return_value=[]), \
         patch("cctv.status.vapix.get_action_rules", return_value=[]), \
         patch("cctv.status.vapix.get_params") as mock_get:
        mock_get.side_effect = [motion_params_response, smb_params_response, storage_params_response, time_params_response]
        result = collect_status(CAM1, camera_config, mock_auth)

    assert result.motion_source == "built-in"


def test_collect_status_motion_source_none_when_no_app(
    camera_config, mock_auth, smb_params_response, motion_params_response,
    storage_params_response, time_params_response,
) -> None:
    """No VMD app installed at all → motion_source is None, not a misleading label."""
    with patch("cctv.status.vapix.get_applications", return_value=[]), \
         patch("cctv.status.vapix.get_action_configurations", return_value=[]), \
         patch("cctv.status.vapix.get_action_rules", return_value=[]), \
         patch("cctv.status.vapix.get_params") as mock_get:
        mock_get.side_effect = [motion_params_response, smb_params_response, storage_params_response, time_params_response]
        result = collect_status(CAM1, camera_config, mock_auth)

    assert result.motion_source is None


def test_collect_status_rule_mismatch_detected(
    camera_config, mock_auth, smb_params_response, motion_params_response,
    storage_params_response, time_params_response,
) -> None:
    """FR35/Story 3.7 real-fleet finding: legacy app installed, but the deployed
    recording rule still targets the built-in topic (not yet migrated by a
    `cctv apply` re-run) → motion_rule_mismatch=True, and the rule's own
    trigger_source correctly reports 'built-in' even though motion_source
    (installed app) says 'legacy app (.eap)'."""
    from cctv.vapix import InstalledApplication, ActionConfiguration, ActionRule
    legacy_app = InstalledApplication(name="VideoMotionDetection", nice_name="AXIS Video Motion Detection", status="Idle")
    cfg = ActionConfiguration(
        config_id=1, name="cctv_motion_record",
        template_token="com.axis.action.unlimited.recording.storage",
        parameters={"storage_id": "NetworkShare", "pre_duration": "5000", "post_duration": "5000"},
    )
    stale_rule = ActionRule(rule_id=1, name="cctv_motion_record", enabled=True,
                             topic="tns1:VideoAnalytics/tnsaxis:MotionDetection//.", primary_action=1)

    with patch("cctv.status.vapix.get_applications", return_value=[legacy_app]), \
         patch("cctv.status.vapix.get_action_configurations", return_value=[cfg]), \
         patch("cctv.status.vapix.get_action_rules", return_value=[stale_rule]), \
         patch("cctv.status.vapix.get_vmd_app_config", return_value=[]), \
         patch("cctv.status.vapix.get_params") as mock_get:
        mock_get.side_effect = [motion_params_response, smb_params_response, storage_params_response, time_params_response]
        result = collect_status(CAM1, camera_config, mock_auth)

    assert result.motion_source == "legacy app (.eap)"
    assert result.action_rules[0].trigger_source == "built-in"
    assert result.motion_rule_mismatch is True


def test_collect_status_rule_matches_source_no_mismatch(
    camera_config, mock_auth, smb_params_response, motion_params_response,
    storage_params_response, time_params_response,
) -> None:
    """Legacy app installed AND the rule already targets the legacy app topic → no mismatch."""
    from cctv.vapix import InstalledApplication, ActionConfiguration, ActionRule
    legacy_app = InstalledApplication(name="VideoMotionDetection", nice_name="AXIS Video Motion Detection", status="Running")
    cfg = ActionConfiguration(
        config_id=1, name="cctv_motion_record",
        template_token="com.axis.action.unlimited.recording.storage",
        parameters={"storage_id": "NetworkShare", "pre_duration": "5000", "post_duration": "5000"},
    )
    migrated_rule = ActionRule(rule_id=1, name="cctv_motion_record", enabled=True,
                                topic="tns1:RuleEngine/tnsaxis:VideoMotionDetection/motion//.", primary_action=1)

    with patch("cctv.status.vapix.get_applications", return_value=[legacy_app]), \
         patch("cctv.status.vapix.get_action_configurations", return_value=[cfg]), \
         patch("cctv.status.vapix.get_action_rules", return_value=[migrated_rule]), \
         patch("cctv.status.vapix.get_vmd_app_config", return_value=[]), \
         patch("cctv.status.vapix.get_params") as mock_get:
        mock_get.side_effect = [motion_params_response, smb_params_response, storage_params_response, time_params_response]
        result = collect_status(CAM1, camera_config, mock_auth)

    assert result.action_rules[0].trigger_source == "legacy app (.eap)"
    assert result.motion_rule_mismatch is False


def test_collect_status_disabled_mismatched_rule_not_flagged(
    camera_config, mock_auth, smb_params_response, motion_params_response,
    storage_params_response, time_params_response,
) -> None:
    """A disabled rule on the wrong topic isn't actionable — must not be flagged as a mismatch."""
    from cctv.vapix import InstalledApplication, ActionConfiguration, ActionRule
    legacy_app = InstalledApplication(name="VideoMotionDetection", nice_name="AXIS Video Motion Detection", status="Idle")
    cfg = ActionConfiguration(
        config_id=1, name="cctv_motion_record",
        template_token="com.axis.action.unlimited.recording.storage",
        parameters={"storage_id": "NetworkShare", "pre_duration": "5000", "post_duration": "5000"},
    )
    disabled_rule = ActionRule(rule_id=1, name="cctv_motion_record", enabled=False,
                                topic="tns1:VideoAnalytics/tnsaxis:MotionDetection//.", primary_action=1)

    with patch("cctv.status.vapix.get_applications", return_value=[legacy_app]), \
         patch("cctv.status.vapix.get_action_configurations", return_value=[cfg]), \
         patch("cctv.status.vapix.get_action_rules", return_value=[disabled_rule]), \
         patch("cctv.status.vapix.get_vmd_app_config", return_value=[]), \
         patch("cctv.status.vapix.get_params") as mock_get:
        mock_get.side_effect = [motion_params_response, smb_params_response, storage_params_response, time_params_response]
        result = collect_status(CAM1, camera_config, mock_auth)

    assert result.motion_rule_mismatch is False


def test_collect_status_non_motion_rule_trigger_source_none(
    camera_config, mock_auth, smb_params_response, motion_params_response,
    storage_params_response, time_params_response, vmd_app_running,
) -> None:
    """A rule on an unrelated topic (e.g. LED control) gets trigger_source=None, not a bogus label."""
    from cctv.vapix import ActionConfiguration, ActionRule
    led_cfg = ActionConfiguration(
        config_id=1, name="Activate LED", template_token="com.axis.action.unlimited.ledcontrol",
        parameters={},
    )
    led_rule = ActionRule(rule_id=1, name="ACC_LED_NetworkShare", enabled=True,
                           topic="tnsaxis:Storage/Disruption//.", primary_action=1)

    with patch("cctv.status.vapix.get_applications", return_value=[vmd_app_running]), \
         patch("cctv.status.vapix.get_action_configurations", return_value=[led_cfg]), \
         patch("cctv.status.vapix.get_action_rules", return_value=[led_rule]), \
         patch("cctv.status.vapix.get_params") as mock_get:
        mock_get.side_effect = [motion_params_response, smb_params_response, storage_params_response, time_params_response]
        result = collect_status(CAM1, camera_config, mock_auth)

    assert result.action_rules[0].trigger_source is None
    assert result.motion_rule_mismatch is False


def test_collect_status_motion_app_version_none_when_no_app(
    camera_config, mock_auth, smb_params_response, motion_params_response,
    storage_params_response, time_params_response,
) -> None:
    """No app installed → motion_app_version is None, not an empty string mistaken for 'no version'."""
    with patch("cctv.status.vapix.get_applications", return_value=[]), \
         patch("cctv.status.vapix.get_action_configurations", return_value=[]), \
         patch("cctv.status.vapix.get_action_rules", return_value=[]), \
         patch("cctv.status.vapix.get_params") as mock_get:
        mock_get.side_effect = [motion_params_response, smb_params_response, storage_params_response, time_params_response]
        result = collect_status(CAM1, camera_config, mock_auth)

    assert result.motion_app_version is None


def test_collect_status_multi_window_shows_all(
    camera_config, mock_auth, smb_params_response, storage_params_response,
    time_params_response, vmd_app_running,
) -> None:
    """Regression (real-hardware finding, 2026-08-03, AXIS M3005 192.168.1.79):
    the app's own native window (e.g. 'DefaultWindow', reduced area, its own
    sensitivity) coexists with a separate full-frame window `cctv apply` added
    later — both must be listed, not just the one cctv manages."""
    multi_window = {
        "root.Motion.M0.Name": "DefaultWindow",
        "root.Motion.M0.Left": "200", "root.Motion.M0.Right": "4000",
        "root.Motion.M0.Top": "200", "root.Motion.M0.Bottom": "4000",
        "root.Motion.M0.Sensitivity": "50",
        "root.Motion.M1.Name": "full_frame",
        "root.Motion.M1.Left": "0", "root.Motion.M1.Right": "9999",
        "root.Motion.M1.Top": "0", "root.Motion.M1.Bottom": "9999",
        "root.Motion.M1.Sensitivity": "95",
    }
    with patch("cctv.status.vapix.get_applications", return_value=[vmd_app_running]), \
         patch("cctv.status.vapix.get_action_configurations", return_value=[]), \
         patch("cctv.status.vapix.get_action_rules", return_value=[]), \
         patch("cctv.status.vapix.get_params") as mock_get:
        mock_get.side_effect = [multi_window, smb_params_response, storage_params_response, time_params_response]
        result = collect_status(CAM1, camera_config, mock_auth)

    assert result.motion_window_detail == (
        "windows: M0 'DefaultWindow' sensitivity 50 | M1 'full_frame' sensitivity 95 (cctv-managed, full-frame)"
    )
    assert result.motion_sensitivity == "95"  # still the cctv-managed window's value


def test_collect_status_single_window_unchanged(
    camera_config, mock_auth, smb_params_response, motion_params_response,
    storage_params_response, time_params_response, vmd_app_running,
) -> None:
    """Single-window cameras keep the simple 'full-frame window' wording — no regression."""
    with patch("cctv.status.vapix.get_applications", return_value=[vmd_app_running]), \
         patch("cctv.status.vapix.get_action_configurations", return_value=[]), \
         patch("cctv.status.vapix.get_action_rules", return_value=[]), \
         patch("cctv.status.vapix.get_params") as mock_get:
        mock_get.side_effect = [motion_params_response, smb_params_response, storage_params_response, time_params_response]
        result = collect_status(CAM1, camera_config, mock_auth)

    assert result.motion_window_detail == "full-frame window"


def test_collect_status_no_motion_app_installed(
    camera_config, mock_auth, smb_params_response, motion_params_response,
    storage_params_response, time_params_response,
) -> None:
    """No VMD app in the applications list → motion_app_* fields are all None, no crash."""
    with patch("cctv.status.vapix.get_applications", return_value=[]), \
         patch("cctv.status.vapix.get_action_configurations", return_value=[]), \
         patch("cctv.status.vapix.get_action_rules", return_value=[]), \
         patch("cctv.status.vapix.get_params") as mock_get:
        mock_get.side_effect = [motion_params_response, smb_params_response, storage_params_response, time_params_response]
        result = collect_status(CAM1, camera_config, mock_auth)

    assert result.motion_app_name is None
    assert result.motion_app_nice_name is None
    assert result.motion_app_status is None


def test_collect_status_empty_motion_group_no_vmd4_profiles_either(
    camera_config, mock_auth, smb_params_response, storage_params_response,
    time_params_response, vmd_app_running,
) -> None:
    """VMD4 camera with root.Motion empty AND no VMD4 profiles configured either
    (e.g. app just installed, nothing set up yet) → no-window/no-sensitivity, not crash."""
    with patch("cctv.status.vapix.get_applications", return_value=[vmd_app_running]), \
         patch("cctv.status.vapix.get_action_configurations", return_value=[]), \
         patch("cctv.status.vapix.get_action_rules", return_value=[]), \
         patch("cctv.status.vapix.get_vmd4_profiles", return_value=[]), \
         patch("cctv.status.vapix.get_params") as mock_get:
        mock_get.side_effect = [{}, smb_params_response, storage_params_response, time_params_response]
        result = collect_status(CAM1, camera_config, mock_auth)

    assert result.motion_enabled is False
    assert result.motion_window_present is False
    assert result.motion_sensitivity is None
    assert result.motion_window_detail is None


def test_collect_status_empty_motion_group_uses_vmd4_profile_fallback(
    camera_config, mock_auth, smb_params_response, storage_params_response,
    time_params_response, vmd_app_running,
) -> None:
    """FR35/Story 3.7 cleanup, real-hardware finding (AXIS M3085-V, 192.168.1.72):
    a motion window exists for the built-in VMD4 app too, it's just configured as
    a profile via the app's own JSON API (local/vmd/control.cgi) rather than
    root.Motion — must be reported as present, not misreported as 'no window'."""
    from cctv.vapix import Vmd4Profile
    profiles = [Vmd4Profile(uid=1, name="Profile 1", camera=1)]
    with patch("cctv.status.vapix.get_applications", return_value=[vmd_app_running]), \
         patch("cctv.status.vapix.get_action_configurations", return_value=[]), \
         patch("cctv.status.vapix.get_action_rules", return_value=[]), \
         patch("cctv.status.vapix.get_vmd4_profiles", return_value=profiles) as mock_vmd4, \
         patch("cctv.status.vapix.get_params") as mock_get:
        mock_get.side_effect = [{}, smb_params_response, storage_params_response, time_params_response]
        result = collect_status(CAM1, camera_config, mock_auth)

    mock_vmd4.assert_called_once_with(CAM1.ip, mock_auth, camera_config.timeout)
    assert result.motion_enabled is True
    assert result.motion_window_present is True
    assert result.motion_window_detail == "profile(s): Profile 1"
    assert result.motion_sensitivity is None  # no single sensitivity knob on VMD4 — expected


def test_collect_status_vmd4_fallback_not_used_for_legacy_app(
    camera_config, mock_auth, smb_params_response, storage_params_response,
    time_params_response,
) -> None:
    """Legacy .eap camera must NOT use the VMD4 JSON API — that endpoint doesn't apply to it."""
    from cctv.vapix import InstalledApplication
    legacy_app = InstalledApplication(name="VideoMotionDetection", nice_name="AXIS Video Motion Detection", status="Idle")
    with patch("cctv.status.vapix.get_applications", return_value=[legacy_app]), \
         patch("cctv.status.vapix.get_action_configurations", return_value=[]), \
         patch("cctv.status.vapix.get_action_rules", return_value=[]), \
         patch("cctv.status.vapix.get_vmd4_profiles") as mock_vmd4, \
         patch("cctv.status.vapix.get_vmd_app_config", return_value=[]), \
         patch("cctv.status.vapix.get_params") as mock_get:
        mock_get.side_effect = [{}, smb_params_response, storage_params_response, time_params_response]
        result = collect_status(CAM1, camera_config, mock_auth)

    mock_vmd4.assert_not_called()
    assert result.motion_window_present is False


def test_collect_status_legacy_app_shows_own_area_not_root_motion(
    camera_config, mock_auth, smb_params_response, motion_params_response,
    storage_params_response, time_params_response,
) -> None:
    """Real-hardware finding (2026-08-04, 3x AXIS M3005/P1204): the legacy .eap's
    OWN polygon detection area (read via vaconfig.cgi) — not root.Motion's window/
    sensitivity — is what actually feeds the Story 3.7-migrated action rule.
    motion_window_detail must reflect the app's own area even though
    root.Motion (motion_params_response fixture) has its own, different,
    now-irrelevant full-frame window — and motion_sensitivity must be None
    (no sensitivity concept in the app's own polygon config)."""
    from cctv.vapix import InstalledApplication, VmdAppArea
    legacy_app = InstalledApplication(name="VideoMotionDetection", nice_name="AXIS Video Motion Detection", status="Running")
    areas = [VmdAppArea(name="Detection Area", points=[(0.6, 0.6), (0.6, -0.6), (-0.6, -0.6), (-0.6, 0.6)])]

    with patch("cctv.status.vapix.get_applications", return_value=[legacy_app]), \
         patch("cctv.status.vapix.get_action_configurations", return_value=[]), \
         patch("cctv.status.vapix.get_action_rules", return_value=[]), \
         patch("cctv.status.vapix.get_vmd_app_config", return_value=areas) as mock_app_config, \
         patch("cctv.status.vapix.get_params") as mock_get:
        mock_get.side_effect = [motion_params_response, smb_params_response, storage_params_response, time_params_response]
        result = collect_status(CAM1, camera_config, mock_auth)

    mock_app_config.assert_called_once_with(CAM1.ip, mock_auth, camera_config.timeout, "VideoMotionDetection")
    assert result.motion_window_present is True
    assert result.motion_window_detail == "app area: 'Detection Area' 60% x 60% area"
    assert result.motion_sensitivity is None
    # must NOT contain root.Motion's own numbers (sensitivity 90, per motion_params_response fixture)
    assert "90" not in (result.motion_window_detail or "")


def test_collect_status_legacy_app_no_areas_configured(
    camera_config, mock_auth, smb_params_response, motion_params_response,
    storage_params_response, time_params_response,
) -> None:
    """Legacy app installed but no detection area configured at all → no window, not a crash."""
    from cctv.vapix import InstalledApplication
    legacy_app = InstalledApplication(name="VideoMotionDetection", nice_name="AXIS Video Motion Detection", status="Idle")
    with patch("cctv.status.vapix.get_applications", return_value=[legacy_app]), \
         patch("cctv.status.vapix.get_action_configurations", return_value=[]), \
         patch("cctv.status.vapix.get_action_rules", return_value=[]), \
         patch("cctv.status.vapix.get_vmd_app_config", return_value=[]), \
         patch("cctv.status.vapix.get_params") as mock_get:
        mock_get.side_effect = [motion_params_response, smb_params_response, storage_params_response, time_params_response]
        result = collect_status(CAM1, camera_config, mock_auth)

    assert result.motion_window_present is False
    assert result.motion_window_detail is None


def test_collect_status_no_action_rules_configured(
    camera_config, mock_auth, smb_params_response, motion_params_response,
    storage_params_response, time_params_response, vmd_app_running,
) -> None:
    with patch("cctv.status.vapix.get_applications", return_value=[vmd_app_running]), \
         patch("cctv.status.vapix.get_action_configurations", return_value=[]), \
         patch("cctv.status.vapix.get_action_rules", return_value=[]), \
         patch("cctv.status.vapix.get_params") as mock_get:
        mock_get.side_effect = [motion_params_response, smb_params_response, storage_params_response, time_params_response]
        result = collect_status(CAM1, camera_config, mock_auth)

    assert result.action_rules == []


def test_collect_status_never_calls_any_write_function(
    camera_config, mock_auth, smb_params_response, motion_params_response,
    storage_params_response, time_params_response, vmd_app_running,
    motion_action_config, motion_action_rule,
) -> None:
    """Core safety property of the whole `status` command: zero write calls, ever."""
    write_patches = [patch(target) for target in _WRITE_PATCH_TARGETS]
    mocks = [p.start() for p in write_patches]
    try:
        with patch("cctv.status.vapix.get_applications", return_value=[vmd_app_running]), \
             patch("cctv.status.vapix.get_action_configurations", return_value=[motion_action_config]), \
             patch("cctv.status.vapix.get_action_rules", return_value=[motion_action_rule]), \
             patch("cctv.status.vapix.get_params") as mock_get:
            mock_get.side_effect = [motion_params_response, smb_params_response, storage_params_response, time_params_response]
            collect_status(CAM1, camera_config, mock_auth)
    finally:
        for p in write_patches:
            p.stop()

    for mock in mocks:
        mock.assert_not_called()


def test_collect_all_isolates_per_camera_failures(camera_config, mock_auth) -> None:
    good = CameraStatusResult(ip=CAM1.ip, model=CAM1.model)
    with patch("cctv.status.collect_status", side_effect=[good, VapixError("Connection timeout")]):
        results = collect_all([CAM1, CAM2], camera_config, mock_auth)

    assert len(results) == 2
    assert results[0].error is None
    assert results[1].ip == CAM2.ip
    assert results[1].model == CAM2.model
    assert results[1].error == "Connection timeout"


def test_collect_all_empty_fleet_returns_empty_list(camera_config, mock_auth) -> None:
    with patch("cctv.status.collect_status") as mock_collect:
        results = collect_all([], camera_config, mock_auth)
    assert results == []
    mock_collect.assert_not_called()


def test_collect_all_non_vapix_exception_also_caught(camera_config, mock_auth) -> None:
    with patch("cctv.status.collect_status", side_effect=Exception("unexpected error")):
        results = collect_all([CAM1], camera_config, mock_auth)
    assert results[0].error == "unexpected error"


def test_collect_all_error_never_contains_credentials(camera_config, mock_auth) -> None:
    error_msg = f"Connection timeout to {CAM1.ip}"
    with patch("cctv.status.collect_status", side_effect=VapixError(error_msg)):
        results = collect_all([CAM1], camera_config, mock_auth)
    assert camera_config.password not in results[0].error
    assert camera_config.smb_password not in results[0].error
