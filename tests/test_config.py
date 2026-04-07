from pathlib import Path

import pytest

from cctv.config import CameraConfig, ConfigError, load_config

VALID_YAML = """\
subnet: 192.168.1.0/24
credentials:
  username: root
  password: testpass
smb:
  ip: 192.168.1.10
  share: /mnt/cctv
  username: smbuser
  password: smbpass
motion_detection:
  enabled: true
  sensitivity: 50
timeout: 5
"""

YAML_WITHOUT_TIMEOUT = """\
subnet: 192.168.1.0/24
credentials:
  username: root
  password: testpass
smb:
  ip: 192.168.1.10
  share: /mnt/cctv
  username: smbuser
  password: smbpass
motion_detection:
  enabled: true
  sensitivity: 50
"""

YAML_EXPLICIT_TIMEOUT = """\
subnet: 192.168.1.0/24
credentials:
  username: root
  password: testpass
smb:
  ip: 192.168.1.10
  share: /mnt/cctv
  username: smbuser
  password: smbpass
motion_detection:
  enabled: true
  sensitivity: 50
timeout: 10
"""


def test_load_valid_config(tmp_path: Path) -> None:
    config_file = tmp_path / "cameras.yaml"
    config_file.write_text(VALID_YAML)
    cfg = load_config(config_file)
    assert isinstance(cfg, CameraConfig)
    assert cfg.subnet == "192.168.1.0/24"
    assert cfg.username == "root"
    assert cfg.password == "testpass"
    assert cfg.smb_ip == "192.168.1.10"
    assert cfg.smb_share == "/mnt/cctv"
    assert cfg.smb_username == "smbuser"
    assert cfg.smb_password == "smbpass"
    assert cfg.motion_enabled is True
    assert cfg.motion_sensitivity == 50
    assert cfg.timeout == 5


def test_timeout_defaults_to_5(tmp_path: Path) -> None:
    config_file = tmp_path / "cameras.yaml"
    config_file.write_text(YAML_WITHOUT_TIMEOUT)
    cfg = load_config(config_file)
    assert cfg.timeout == 5


def test_load_config_explicit_timeout(tmp_path: Path) -> None:
    config_file = tmp_path / "cameras.yaml"
    config_file.write_text(YAML_EXPLICIT_TIMEOUT)
    cfg = load_config(config_file)
    assert cfg.timeout == 10


# --- Validation error cases (Story 1.3) ---


def test_file_not_found() -> None:
    with pytest.raises(ConfigError, match="not found"):
        load_config(Path("nonexistent_file_xyz_cctv.yaml"))


def test_empty_file(tmp_path: Path) -> None:
    config_file = tmp_path / "cameras.yaml"
    config_file.write_text("")
    with pytest.raises(ConfigError, match="empty"):
        load_config(config_file)


def test_missing_top_level_key(tmp_path: Path) -> None:
    # Missing 'smb' section
    yaml_content = """\
subnet: 192.168.1.0/24
credentials:
  username: root
  password: testpass
motion_detection:
  enabled: true
  sensitivity: 50
"""
    config_file = tmp_path / "cameras.yaml"
    config_file.write_text(yaml_content)
    with pytest.raises(ConfigError, match="smb"):
        load_config(config_file)


def test_missing_nested_key(tmp_path: Path) -> None:
    # smb section present but missing 'ip'
    yaml_content = """\
subnet: 192.168.1.0/24
credentials:
  username: root
  password: testpass
smb:
  share: /mnt/cctv
  username: smbuser
  password: smbpass
motion_detection:
  enabled: true
  sensitivity: 50
"""
    config_file = tmp_path / "cameras.yaml"
    config_file.write_text(yaml_content)
    with pytest.raises(ConfigError, match="smb.ip"):
        load_config(config_file)


def test_invalid_subnet(tmp_path: Path) -> None:
    yaml_content = VALID_YAML.replace("192.168.1.0/24", "not-a-cidr")
    config_file = tmp_path / "cameras.yaml"
    config_file.write_text(yaml_content)
    with pytest.raises(ConfigError, match="not-a-cidr"):
        load_config(config_file)


def test_invalid_yaml_syntax(tmp_path: Path) -> None:
    config_file = tmp_path / "cameras.yaml"
    config_file.write_text("{bad: [yaml")
    with pytest.raises(ConfigError):
        load_config(config_file)


def test_recording_retention_days_defaults_to_33(tmp_path: Path) -> None:
    config_file = tmp_path / "cameras.yaml"
    config_file.write_text(VALID_YAML)
    cfg = load_config(config_file)
    assert cfg.recording_retention_days == 33


def test_recording_retention_days_explicit(tmp_path: Path) -> None:
    yaml_content = VALID_YAML + "recording_retention_days: 14\n"
    config_file = tmp_path / "cameras.yaml"
    config_file.write_text(yaml_content)
    cfg = load_config(config_file)
    assert cfg.recording_retention_days == 14


def test_timeout_null_value(tmp_path: Path) -> None:
    # 'timeout:' with no value → yaml.safe_load gives None → should default to 5
    yaml_content = VALID_YAML + "timeout:\n"
    # The VALID_YAML already has timeout: 5, so build from YAML_WITHOUT_TIMEOUT
    yaml_content = YAML_WITHOUT_TIMEOUT + "timeout:\n"
    config_file = tmp_path / "cameras.yaml"
    config_file.write_text(yaml_content)
    cfg = load_config(config_file)
    assert cfg.timeout == 5
