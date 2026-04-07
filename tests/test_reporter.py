from __future__ import annotations

from cctv.reconciler import CameraResult, CameraStatus
from cctv.reporter import print_apply_results, print_camera_list
from cctv.scanner import DiscoveredCamera


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
