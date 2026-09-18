from __future__ import annotations

from cctv.reconciler import CameraResult, CameraStatus
from cctv.reporter import print_apply_results, print_camera_list, print_camera_status
from cctv.scanner import DiscoveredCamera
from cctv.status import CameraStatusResult, ActionRuleStatus


CAM_A = DiscoveredCamera(ip="192.168.1.101", model="AXIS P3245-V")
CAM_B = DiscoveredCamera(ip="192.168.1.102", model="AXIS Q6135-LE")


def test_print_camera_list_single_camera(capsys) -> None:
    print_camera_list([CAM_A])
    out = capsys.readouterr().out
    assert "192.168.1.101" in out
    assert "AXIS P3245-V" in out
    assert "(reachable)" in out
    assert "Found 1 Axis camera\n" in out  # singular, no trailing 's'


def test_print_camera_list_multiple_cameras(capsys) -> None:
    print_camera_list([CAM_A, CAM_B])
    out = capsys.readouterr().out
    assert "192.168.1.101" in out
    assert "192.168.1.102" in out
    assert "AXIS P3245-V" in out
    assert "AXIS Q6135-LE" in out
    assert "Found 2 Axis cameras\n" in out  # plural


def test_print_camera_list_empty(capsys) -> None:
    print_camera_list([])
    out = capsys.readouterr().out
    assert "No Axis cameras found" in out
    assert "(reachable)" not in out


def test_print_camera_list_format(capsys) -> None:
    print_camera_list([CAM_A])
    out = capsys.readouterr().out
    lines = out.splitlines()
    # First line: camera details
    assert "192.168.1.101" in lines[0]
    assert "AXIS P3245-V" in lines[0]
    assert "(reachable)" in lines[0]
    # Second line: summary
    assert "Found 1 Axis camera" in lines[1]


# --- print_apply_results tests (Story 3.5) ---

_IP = "192.168.1.101"
_MODEL = "AXIS P3245-V"


def _result(status: CameraStatus, settings: list[str] | None = None, error: str | None = None) -> CameraResult:
    return CameraResult(ip=_IP, model=_MODEL, status=status, settings_changed=settings or [], error=error)


def test_print_apply_results_applied(capsys) -> None:
    exit_code = print_apply_results([_result(CameraStatus.APPLIED, ["smb_ip", "motion"])])
    out = capsys.readouterr().out
    assert f"{_IP}  {_MODEL}  applied (smb_ip, motion)" in out
    assert exit_code == 0


def test_print_apply_results_no_change(capsys) -> None:
    exit_code = print_apply_results([_result(CameraStatus.NO_CHANGE)])
    out = capsys.readouterr().out
    assert "no change" in out
    assert exit_code == 0


def test_print_apply_results_failed(capsys) -> None:
    exit_code = print_apply_results([_result(CameraStatus.FAILED, error="Connection timeout")])
    out = capsys.readouterr().out
    assert f"{_IP}  {_MODEL}  FAILED — Connection timeout" in out
    assert exit_code == 1


def test_print_apply_results_summary_counts(capsys) -> None:
    results = [
        _result(CameraStatus.APPLIED, ["smb_ip"]),
        _result(CameraStatus.APPLIED, ["motion"]),
        _result(CameraStatus.NO_CHANGE),
        _result(CameraStatus.FAILED, error="timeout"),
    ]
    print_apply_results(results)
    out = capsys.readouterr().out
    assert "Summary:" in out
    assert "2 applied" in out
    assert "1 no change" in out
    assert "1 failed" in out


def test_print_apply_results_exit_0_all_succeed(capsys) -> None:
    results = [_result(CameraStatus.APPLIED, ["smb_ip"]), _result(CameraStatus.NO_CHANGE)]
    exit_code = print_apply_results(results)
    assert exit_code == 0


def test_print_apply_results_exit_1_any_failed(capsys) -> None:
    results = [_result(CameraStatus.APPLIED, ["smb_ip"]), _result(CameraStatus.FAILED, error="timeout")]
    exit_code = print_apply_results(results)
    assert exit_code == 1


def test_print_apply_results_rerun_hint_when_failed(capsys) -> None:
    print_apply_results([_result(CameraStatus.FAILED, error="timeout")])
    out = capsys.readouterr().out
    assert "re-run" in out


def test_print_apply_results_empty(capsys) -> None:
    exit_code = print_apply_results([])
    out = capsys.readouterr().out
    assert "0 applied" in out
    assert "0 no change" in out
    assert "0 failed" in out
    assert exit_code == 0


# --- print_camera_status tests (Story 4.1) ---

def _full_status() -> CameraStatusResult:
    return CameraStatusResult(
        ip=_IP,
        model=_MODEL,
        motion_app_name="vmd",
        motion_app_nice_name="AXIS Video Motion Detection",
        motion_app_status="Running",
        motion_enabled=True,
        motion_sensitivity="90",
        motion_window_present=True,
        motion_window_detail="full-frame window",
        action_rules=[ActionRuleStatus(
            name="cctv_motion_record", topic="tns1:VideoAnalytics/tnsaxis:MotionDetection",
            enabled=True, target_template="com.axis.action.unlimited.recording.storage",
            pre_duration_ms="5000", post_duration_ms="2000",
        )],
        smb_ip="192.168.1.10", smb_share="/mnt/cctv", smb_username="smbuser",
        timezone="MSK-3", retention_days="33",
    )


def test_print_camera_status_full_block(capsys, camera_config) -> None:
    exit_code = print_camera_status([_full_status()])
    out = capsys.readouterr().out
    assert f"{_IP}  {_MODEL}" in out
    assert "vmd (AXIS Video Motion Detection) — Running" in out
    assert "enabled, sensitivity 90, full-frame window" in out
    assert "cctv_motion_record" in out
    assert "pre 5000ms, post 2000ms" in out
    assert "192.168.1.10:/mnt/cctv" in out
    assert "smbuser" in out
    assert "MSK-3" in out
    assert "33 days" in out
    assert exit_code == 0


def test_print_camera_status_credentials_never_printed(capsys, camera_config) -> None:
    print_camera_status([_full_status()])
    out = capsys.readouterr().out
    assert camera_config.profiles[0].storage.smb.password not in out
    assert camera_config.password not in out


def test_print_camera_status_motion_source_shown(capsys) -> None:
    """FR35/Story 3.7: motion_source is appended in brackets after the app status."""
    result = CameraStatusResult(
        ip=_IP, model=_MODEL, smb_ip="1.2.3.4", smb_share="/x", smb_username="u",
        timezone="UTC0", retention_days="33",
        motion_app_name="VideoMotionDetection", motion_app_nice_name="AXIS Video Motion Detection",
        motion_app_status="Idle", motion_source="legacy app (.eap)",
    )
    print_camera_status([result])
    out = capsys.readouterr().out
    assert "VideoMotionDetection (AXIS Video Motion Detection) — Idle [legacy app (.eap)]" in out


def test_print_camera_status_no_motion_source_no_brackets(capsys) -> None:
    """motion_source=None (e.g. legacy CameraStatusResult without it set) → no stray '[None]' suffix."""
    result = CameraStatusResult(
        ip=_IP, model=_MODEL, smb_ip="1.2.3.4", smb_share="/x", smb_username="u",
        timezone="UTC0", retention_days="33",
        motion_app_name="vmd", motion_app_nice_name="AXIS Video Motion Detection",
        motion_app_status="Running", motion_source=None,
    )
    print_camera_status([result])
    out = capsys.readouterr().out
    assert "vmd (AXIS Video Motion Detection) — Running" in out
    assert "[None]" not in out
    assert "[" not in out.split("motion app:")[1].split("\n")[0]


def test_print_camera_status_rule_trigger_source_shown(capsys) -> None:
    result = CameraStatusResult(
        ip=_IP, model=_MODEL, smb_ip="1.2.3.4", smb_share="/x", smb_username="u",
        timezone="UTC0", retention_days="33",
        action_rules=[ActionRuleStatus(
            name="cctv_motion_record", topic="tns1:RuleEngine/tnsaxis:VideoMotionDetection/motion",
            enabled=True, target_template="com.axis.action.unlimited.recording.storage",
            pre_duration_ms="5000", post_duration_ms="2000", trigger_source="legacy app (.eap)",
        )],
    )
    print_camera_status([result])
    out = capsys.readouterr().out
    assert "[trigger: legacy app (.eap)]" in out


def test_print_camera_status_mismatch_warning_shown(capsys) -> None:
    result = CameraStatusResult(
        ip=_IP, model=_MODEL, smb_ip="1.2.3.4", smb_share="/x", smb_username="u",
        timezone="UTC0", retention_days="33",
        motion_app_name="VideoMotionDetection", motion_app_nice_name="AXIS Video Motion Detection",
        motion_app_status="Idle", motion_source="legacy app (.eap)",
        motion_rule_mismatch=True,
    )
    print_camera_status([result])
    out = capsys.readouterr().out
    assert "MISMATCH" in out
    assert "cctv apply" in out


def test_print_camera_status_no_mismatch_no_warning_line(capsys) -> None:
    exit_code = print_camera_status([_full_status()])
    out = capsys.readouterr().out
    assert "MISMATCH" not in out
    assert exit_code == 0


def test_print_camera_status_app_version_shown(capsys) -> None:
    result = CameraStatusResult(
        ip=_IP, model=_MODEL, smb_ip="1.2.3.4", smb_share="/x", smb_username="u",
        timezone="UTC0", retention_days="33",
        motion_app_name="VideoMotionDetection", motion_app_nice_name="AXIS Video Motion Detection",
        motion_app_status="Idle", motion_app_version="2.2",
    )
    print_camera_status([result])
    out = capsys.readouterr().out
    assert "VideoMotionDetection v2.2 (AXIS Video Motion Detection) — Idle" in out


def test_print_camera_status_no_app_version_no_v_suffix(capsys) -> None:
    result = CameraStatusResult(
        ip=_IP, model=_MODEL, smb_ip="1.2.3.4", smb_share="/x", smb_username="u",
        timezone="UTC0", retention_days="33",
        motion_app_name="vmd", motion_app_nice_name="AXIS Video Motion Detection",
        motion_app_status="Running", motion_app_version=None,
    )
    print_camera_status([result])
    out = capsys.readouterr().out
    assert "vmd (AXIS Video Motion Detection) — Running" in out
    assert "vNone" not in out


def test_print_camera_status_multi_window_no_redundant_sensitivity(capsys) -> None:
    result = CameraStatusResult(
        ip=_IP, model=_MODEL, smb_ip="1.2.3.4", smb_share="/x", smb_username="u",
        timezone="UTC0", retention_days="33",
        motion_enabled=True, motion_sensitivity="95",
        motion_window_detail="windows: M0 'DefaultWindow' sensitivity 50 | M1 'full_frame' sensitivity 95 (cctv-managed, full-frame)",
    )
    print_camera_status([result])
    out = capsys.readouterr().out
    assert "motion:       enabled, windows: M0 'DefaultWindow' sensitivity 50 | M1 'full_frame' sensitivity 95 (cctv-managed, full-frame)" in out
    # top-level "sensitivity 95" preamble must not duplicate what's already in the windows list
    assert "enabled, sensitivity 95, windows:" not in out


def test_print_camera_status_no_motion_app(capsys) -> None:
    """No app installed is flagged as an incorrect setup, not neutral 'not installed' info."""
    result = CameraStatusResult(ip=_IP, model=_MODEL, smb_ip="1.2.3.4", smb_share="/x", smb_username="u",
                                 timezone="UTC0", retention_days="33")
    print_camera_status([result])
    out = capsys.readouterr().out
    assert "motion app:   NOT INSTALLED" in out


def test_print_camera_status_vmd4_profile_window_shown(capsys) -> None:
    """FR35/Story 3.7 cleanup: built-in VMD4 camera with no root.Motion window still
    shows its profile-based window, instead of a misleading 'no window configured'."""
    result = CameraStatusResult(
        ip=_IP, model=_MODEL, smb_ip="1.2.3.4", smb_share="/x", smb_username="u",
        timezone="UTC0", retention_days="33",
        motion_app_name="vmd", motion_app_nice_name="AXIS Video Motion Detection",
        motion_app_status="Running", motion_source="built-in",
        motion_enabled=True, motion_sensitivity=None,
        motion_window_present=True, motion_window_detail="profile(s): Profile 1",
    )
    print_camera_status([result])
    out = capsys.readouterr().out
    assert "motion:       enabled, profile(s): Profile 1" in out
    assert "sensitivity" not in out.split("motion:")[1].split("\n")[0]


def test_print_camera_status_action_rule_without_durations(capsys) -> None:
    """Regression (real-hardware finding): a non-recording action rule (e.g. LED control)
    has no pre/post duration params — must print 'n/a', not 'Nonems'."""
    result = CameraStatusResult(
        ip=_IP, model=_MODEL, smb_ip="1.2.3.4", smb_share="/x", smb_username="u",
        timezone="UTC0", retention_days="33",
        action_rules=[ActionRuleStatus(
            name="ACC_LED_NetworkShare", topic="tns1:Storage/tnsaxis:NetworkShare",
            enabled=True, target_template="com.axis.action.unlimited.ledcontrol",
            pre_duration_ms=None, post_duration_ms=None,
        )],
    )
    print_camera_status([result])
    out = capsys.readouterr().out
    assert "pre n/a, post n/a" in out
    assert "None" not in out


def test_print_camera_status_no_action_rules(capsys) -> None:
    result = CameraStatusResult(ip=_IP, model=_MODEL, smb_ip="1.2.3.4", smb_share="/x", smb_username="u",
                                 timezone="UTC0", retention_days="33", action_rules=[])
    print_camera_status([result])
    out = capsys.readouterr().out
    assert "action rules: none configured" in out


def test_print_camera_status_failed_camera_single_line(capsys) -> None:
    result = CameraStatusResult(ip=_IP, model=_MODEL, error="Connection timeout to " + _IP)
    exit_code = print_camera_status([result])
    out = capsys.readouterr().out
    assert f"{_IP}  {_MODEL}  STATUS UNAVAILABLE — Connection timeout to {_IP}" in out
    assert "motion app:" not in out
    assert exit_code == 1


def test_print_camera_status_mixed_success_and_failure_exit_1(capsys) -> None:
    exit_code = print_camera_status([_full_status(), CameraStatusResult(ip="1.2.3.4", model="X", error="boom")])
    assert exit_code == 1


def test_print_camera_status_all_succeed_exit_0(capsys) -> None:
    exit_code = print_camera_status([_full_status(), _full_status()])
    assert exit_code == 0


def test_print_camera_status_empty(capsys) -> None:
    exit_code = print_camera_status([])
    out = capsys.readouterr().out
    assert "No Axis cameras found" in out
    assert exit_code == 0
