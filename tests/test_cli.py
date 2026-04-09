from pathlib import Path
from unittest.mock import patch

from typer.testing import CliRunner

from cctv.cli import app
from cctv.reconciler import CameraResult, CameraStatus
from cctv.scanner import DiscoveredCamera

runner = CliRunner(env={"NO_COLOR": "1"})

VALID_CONFIG = """\
subnet: 192.168.1.0/24
timeout: 5
credentials:
  username: root
  password: pass
smb:
  ip: 192.168.1.10
  share: /recordings
  username: smbuser
  password: smbpass
motion_detection:
  enabled: true
  sensitivity: 50
"""


def test_help_shows_commands() -> None:
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    assert "list" in result.output
    assert "apply" in result.output


def test_list_help() -> None:
    result = runner.invoke(app, ["list", "--help"])
    assert result.exit_code == 0
    assert "--subnet" in result.output


def test_apply_help() -> None:
    result = runner.invoke(app, ["apply", "--help"])
    assert result.exit_code == 0
    assert "config" in result.output
    assert "--subnet" in result.output


# --- Validation integration tests (Story 1.3) ---


def test_apply_missing_config_file() -> None:
    result = runner.invoke(app, ["apply", "nonexistent_xyz_cctv.yaml"])
    assert result.exit_code != 0


def test_apply_invalid_config(tmp_path: Path) -> None:
    bad = tmp_path / "bad.yaml"
    bad.write_text("subnet: 192.168.1.0/24\n")  # missing smb, credentials, motion_detection
    result = runner.invoke(app, ["apply", str(bad)])
    assert result.exit_code == 2


# --- list command output tests (Story 2.2) ---


def test_list_cameras_outputs_per_camera_lines(tmp_path: Path) -> None:
    cfg = tmp_path / "cameras.yaml"
    cfg.write_text(VALID_CONFIG)
    cameras = [DiscoveredCamera(ip="192.168.1.101", model="AXIS P3245-V")]
    with patch("cctv.cli.scanner.scan", return_value=cameras):
        result = runner.invoke(app, ["list", str(cfg)])
    assert result.exit_code == 0
    assert "192.168.1.101" in result.output
    assert "AXIS P3245-V" in result.output
    assert "(reachable)" in result.output


def test_list_cameras_shows_count(tmp_path: Path) -> None:
    cfg = tmp_path / "cameras.yaml"
    cfg.write_text(VALID_CONFIG)
    cameras = [
        DiscoveredCamera(ip="192.168.1.101", model="AXIS P3245-V"),
        DiscoveredCamera(ip="192.168.1.102", model="AXIS Q6135-LE"),
    ]
    with patch("cctv.cli.scanner.scan", return_value=cameras):
        result = runner.invoke(app, ["list", str(cfg)])
    assert result.exit_code == 0
    assert "Found 2 Axis cameras" in result.output


def test_list_cameras_exits_2_when_no_cameras(tmp_path: Path) -> None:
    cfg = tmp_path / "cameras.yaml"
    cfg.write_text(VALID_CONFIG)
    with patch("cctv.cli.scanner.scan", return_value=[]):
        result = runner.invoke(app, ["list", str(cfg)])
    assert result.exit_code == 2
    assert "No Axis cameras found" in result.output


def test_apply_runs_executor(tmp_path: Path) -> None:
    cfg = tmp_path / "cameras.yaml"
    cfg.write_text(VALID_CONFIG)
    cameras = [DiscoveredCamera(ip="192.168.1.101", model="AXIS P3245-V")]
    results = [CameraResult(ip="192.168.1.101", model="AXIS P3245-V", status=CameraStatus.APPLIED, settings_changed=["smb_ip"])]
    with patch("cctv.cli.scanner.scan", return_value=cameras), \
         patch("cctv.cli.executor.apply_all", return_value=results) as mock_exec:
        result = runner.invoke(app, ["apply", str(cfg)])
    assert result.exit_code == 0
    mock_exec.assert_called_once()
    call_cameras, call_cfg, call_auth = mock_exec.call_args[0]
    assert call_cameras == cameras
    assert call_cfg.subnet == "192.168.1.0/24"


def test_apply_exits_1_when_cameras_fail(tmp_path: Path) -> None:
    cfg = tmp_path / "cameras.yaml"
    cfg.write_text(VALID_CONFIG)
    cameras = [DiscoveredCamera(ip="192.168.1.101", model="AXIS P3245-V")]
    results = [CameraResult(ip="192.168.1.101", model="AXIS P3245-V", status=CameraStatus.FAILED, error="timeout")]
    with patch("cctv.cli.scanner.scan", return_value=cameras), \
         patch("cctv.cli.executor.apply_all", return_value=results):
        result = runner.invoke(app, ["apply", str(cfg)])
    assert result.exit_code == 1
    assert "FAILED" in result.output
    assert "re-run" in result.output


def test_list_cameras_subnet_override(tmp_path: Path) -> None:
    cfg = tmp_path / "cameras.yaml"
    cfg.write_text(VALID_CONFIG)
    with patch("cctv.cli.scanner.scan", return_value=[]) as mock_scan:
        result = runner.invoke(app, ["list", str(cfg), "--subnet", "10.0.0.0/24"])
    mock_scan.assert_called_once()
    assert mock_scan.call_args[0][0] == "10.0.0.0/24"
    assert result.exit_code == 2
