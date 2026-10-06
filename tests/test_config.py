from pathlib import Path

import pytest

from cctv.config import CameraConfig, ConfigError, load_config

VALID_YAML = """\
subnet: 192.168.1.0/24
credentials:
  username: root
  password: testpass
timeout: 5
profiles:
  - name: legacy-smb
    match:
      models: [M3005, P1204]
    motion_detection:
      enabled: true
      sensitivity: 50
    storage:
      backend: smb
      smb:
        ip: 192.168.1.10
        share: /mnt/cctv
        username: smbuser
        password: smbpass
"""

YAML_WITHOUT_TIMEOUT = VALID_YAML.replace("timeout: 5\n", "")

YAML_EXPLICIT_TIMEOUT = VALID_YAML.replace("timeout: 5\n", "timeout: 10\n")

S3_PROFILE_YAML = """\
  - name: m3085v-sd-s3sync
    match:
      models: [M3085-V]
    target_firmware: "12.11.72"
    applications:
      sd_to_s3_sync:
        app_package_path: /opt/eap/signed_SD_to_S3_Sync_0_9_5_aarch64.eap
    motion_detection:
      enabled: true
      size_percentage: [5, 5]
      time_short_lived_limit: 1
      distance_swaying_object: 5
    storage:
      backend: sd_s3sync
      sd_s3sync:
        endpoint: https://s3.example-provider.com
        region: us-east-1
        bucket: my-cctv-bucket
        access_key: AKIA
        secret_key: SECRET
"""


def test_load_valid_config(tmp_path: Path) -> None:
    config_file = tmp_path / "cameras.yaml"
    config_file.write_text(VALID_YAML)
    cfg = load_config(config_file)
    assert isinstance(cfg, CameraConfig)
    assert cfg.subnet == "192.168.1.0/24"
    assert cfg.username == "root"
    assert cfg.password == "testpass"
    assert cfg.timeout == 5

    assert len(cfg.profiles) == 1
    profile = cfg.profiles[0]
    assert profile.name == "legacy-smb"
    assert profile.models == ["M3005", "P1204"]
    assert profile.target_firmware == []
    assert profile.applications == {}
    assert profile.motion_detection["enabled"] is True
    assert profile.motion_detection["sensitivity"] == 50
    assert profile.storage.backend == "smb"
    assert profile.storage.sd_s3sync is None
    assert profile.storage.smb.ip == "192.168.1.10"
    assert profile.storage.smb.share == "/mnt/cctv"
    assert profile.storage.smb.username == "smbuser"
    assert profile.storage.smb.password == "smbpass"


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
    yaml_content = """\
subnet: 192.168.1.0/24
credentials:
  username: root
  password: testpass
"""
    config_file = tmp_path / "cameras.yaml"
    config_file.write_text(yaml_content)
    with pytest.raises(ConfigError, match="profiles"):
        load_config(config_file)


def test_missing_nested_key(tmp_path: Path) -> None:
    """storage.smb present but missing 'ip' → error names the full path."""
    yaml_content = VALID_YAML.replace("        ip: 192.168.1.10\n", "")
    config_file = tmp_path / "cameras.yaml"
    config_file.write_text(yaml_content)
    with pytest.raises(ConfigError, match=r"profiles\[0\]\.storage\.smb\.ip"):
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


def test_motion_detection_kept_as_opaque_mapping(tmp_path: Path) -> None:
    """motion_detection shape varies by camera generation, so config.py passes it
    through untouched rather than pinning it to the legacy sensitivity schema."""
    yaml_content = VALID_YAML.replace(
        "      sensitivity: 50",
        "      sensitivity: 50\n      pre_trigger_time: 10\n      post_trigger_time: 15",
    )
    config_file = tmp_path / "cameras.yaml"
    config_file.write_text(yaml_content)
    cfg = load_config(config_file)
    assert cfg.profiles[0].motion_detection == {
        "enabled": True,
        "sensitivity": 50,
        "pre_trigger_time": 10,
        "post_trigger_time": 15,
    }


def test_timezone_optional_defaults_to_none(tmp_path: Path) -> None:
    config_file = tmp_path / "cameras.yaml"
    config_file.write_text(VALID_YAML)
    cfg = load_config(config_file)
    assert cfg.timezone is None


def test_timezone_loaded_when_present(tmp_path: Path) -> None:
    yaml_content = VALID_YAML + "timezone: CET-1CEST,M3.5.0,M10.5.0/3\n"
    config_file = tmp_path / "cameras.yaml"
    config_file.write_text(yaml_content)
    cfg = load_config(config_file)
    assert cfg.timezone == "CET-1CEST,M3.5.0,M10.5.0/3"


def test_timeout_null_value(tmp_path: Path) -> None:
    """'timeout:' with no value → yaml.safe_load gives None → defaults to 5."""
    yaml_content = YAML_WITHOUT_TIMEOUT + "timeout:\n"
    config_file = tmp_path / "cameras.yaml"
    config_file.write_text(yaml_content)
    cfg = load_config(config_file)
    assert cfg.timeout == 5


# --- Fleet-wide NTP fallback ---


def test_ntp_fallback_servers_default_empty(tmp_path: Path) -> None:
    config_file = tmp_path / "cameras.yaml"
    config_file.write_text(VALID_YAML)
    cfg = load_config(config_file)
    assert cfg.ntp_fallback_servers == []


def test_ntp_fallback_servers_loaded_when_present(tmp_path: Path) -> None:
    yaml_content = VALID_YAML + "ntp_fallback_servers: [pool.ntp.org, ntp1.vniiftri.ru]\n"
    config_file = tmp_path / "cameras.yaml"
    config_file.write_text(yaml_content)
    cfg = load_config(config_file)
    assert cfg.ntp_fallback_servers == ["pool.ntp.org", "ntp1.vniiftri.ru"]


def test_ntp_fallback_servers_scalar_rejected(tmp_path: Path) -> None:
    yaml_content = VALID_YAML + "ntp_fallback_servers: pool.ntp.org\n"
    config_file = tmp_path / "cameras.yaml"
    config_file.write_text(yaml_content)
    with pytest.raises(ConfigError, match="ntp_fallback_servers"):
        load_config(config_file)


# --- Profiles ---


def test_profiles_must_be_non_empty_list(tmp_path: Path) -> None:
    yaml_content = VALID_YAML.split("profiles:")[0] + "profiles: []\n"
    config_file = tmp_path / "cameras.yaml"
    config_file.write_text(yaml_content)
    with pytest.raises(ConfigError, match="non-empty"):
        load_config(config_file)


def test_second_profile_parsed_with_s3_backend(tmp_path: Path) -> None:
    config_file = tmp_path / "cameras.yaml"
    config_file.write_text(VALID_YAML + S3_PROFILE_YAML)
    cfg = load_config(config_file)

    assert len(cfg.profiles) == 2
    s3 = cfg.profiles[1]
    assert s3.name == "m3085v-sd-s3sync"
    assert s3.target_firmware == ["12.11.72"]
    assert s3.applications["sd_to_s3_sync"]["app_package_path"].endswith(".eap")
    assert s3.motion_detection["size_percentage"] == [5, 5]
    assert s3.storage.backend == "sd_s3sync"
    assert s3.storage.smb is None
    assert s3.storage.sd_s3sync.endpoint == "https://s3.example-provider.com"
    assert s3.storage.sd_s3sync.bucket == "my-cctv-bucket"
    assert s3.storage.sd_s3sync.access_key == "AKIA"
    assert s3.storage.sd_s3sync.secret_key == "SECRET"


def test_unknown_storage_backend_rejected(tmp_path: Path) -> None:
    yaml_content = VALID_YAML.replace("backend: smb", "backend: ftp")
    config_file = tmp_path / "cameras.yaml"
    config_file.write_text(yaml_content)
    with pytest.raises(ConfigError, match="storage.backend"):
        load_config(config_file)


def test_backend_block_must_match_declared_backend(tmp_path: Path) -> None:
    """backend: sd_s3sync with only an smb block → the sd_s3sync block is required."""
    yaml_content = VALID_YAML.replace("backend: smb", "backend: sd_s3sync")
    config_file = tmp_path / "cameras.yaml"
    config_file.write_text(yaml_content)
    with pytest.raises(ConfigError, match="storage.sd_s3sync is required"):
        load_config(config_file)


def test_missing_s3_credential_key_rejected(tmp_path: Path) -> None:
    yaml_content = VALID_YAML + S3_PROFILE_YAML.replace("        secret_key: SECRET\n", "")
    config_file = tmp_path / "cameras.yaml"
    config_file.write_text(yaml_content)
    with pytest.raises(ConfigError, match=r"profiles\[1\]\.storage\.sd_s3sync\.secret_key"):
        load_config(config_file)


def test_profile_missing_match_rejected(tmp_path: Path) -> None:
    yaml_content = VALID_YAML.replace("    match:\n      models: [M3005, P1204]\n", "")
    config_file = tmp_path / "cameras.yaml"
    config_file.write_text(yaml_content)
    with pytest.raises(ConfigError, match=r"profiles\[0\]\.match"):
        load_config(config_file)


def test_profile_empty_models_rejected(tmp_path: Path) -> None:
    yaml_content = VALID_YAML.replace("models: [M3005, P1204]", "models: []")
    config_file = tmp_path / "cameras.yaml"
    config_file.write_text(yaml_content)
    with pytest.raises(ConfigError, match="models"):
        load_config(config_file)


# --- Profile matching ---


def test_match_profile_substring_matches_full_model_string(tmp_path: Path) -> None:
    """Discovered models come back as full product names ('AXIS M3085-V Network
    Camera'), so match.models entries are substrings, not exact values."""
    config_file = tmp_path / "cameras.yaml"
    config_file.write_text(VALID_YAML + S3_PROFILE_YAML)
    cfg = load_config(config_file)

    assert cfg.match_profile("AXIS M3085-V Network Camera").name == "m3085v-sd-s3sync"
    assert cfg.match_profile("AXIS M3005 Fixed Dome").name == "legacy-smb"


def test_match_profile_returns_first_match(tmp_path: Path) -> None:
    """Overlapping profiles resolve to the first one declared, not the most specific."""
    overlapping = VALID_YAML.replace("models: [M3005, P1204]", "models: [M30]")
    config_file = tmp_path / "cameras.yaml"
    config_file.write_text(overlapping + S3_PROFILE_YAML)
    cfg = load_config(config_file)

    assert cfg.match_profile("AXIS M3085-V Network Camera").name == "legacy-smb"


def test_match_profile_returns_none_when_nothing_matches(tmp_path: Path) -> None:
    config_file = tmp_path / "cameras.yaml"
    config_file.write_text(VALID_YAML)
    cfg = load_config(config_file)
    assert cfg.match_profile("AXIS Q6135-LE PTZ") is None
    assert cfg.match_profile("") is None


# ---------------------------------------------------------------------------
# syslog
# ---------------------------------------------------------------------------


def _load_with_syslog(tmp_path: Path, block: str) -> CameraConfig:
    config_file = tmp_path / "cameras.yaml"
    config_file.write_text(VALID_YAML + block)
    return load_config(config_file)


def test_syslog_omitted_is_none(tmp_path: Path) -> None:
    assert _load_with_syslog(tmp_path, "").syslog is None


def test_syslog_defaults(tmp_path: Path) -> None:
    cfg = _load_with_syslog(tmp_path, "syslog:\n  host: 192.168.1.100\n")
    assert cfg.syslog is not None
    assert (cfg.syslog.host, cfg.syslog.port, cfg.syslog.severity) == ("192.168.1.100", 514, "info")


def test_syslog_explicit_values(tmp_path: Path) -> None:
    cfg = _load_with_syslog(tmp_path, "syslog:\n  host: nas.lan\n  port: 1514\n  severity: warning\n")
    assert (cfg.syslog.host, cfg.syslog.port, cfg.syslog.severity) == ("nas.lan", 1514, "warning")


@pytest.mark.parametrize("block, match", [
    ("syslog: 192.168.1.100\n", "'syslog' must be a YAML mapping"),
    ("syslog:\n  port: 514\n", "syslog.host"),
    ("syslog:\n  host: ''\n", "syslog.host"),
    ("syslog:\n  host: 'nas lan'\n", "syslog.host"),
    ("syslog:\n  host: 'nas.lan:514'\n", "syslog.host"),
    ("syslog:\n  host: '@nas'\n", "syslog.host"),
    ("syslog:\n  host: \"nas\\n*.* |/tmp/pipe\"\n", "syslog.host"),
    ("syslog:\n  host: nas\n  port: 0\n", "syslog.port"),
    ("syslog:\n  host: nas\n  port: 70000\n", "syslog.port"),
    ("syslog:\n  host: nas\n  port: '514'\n", "syslog.port"),
    ("syslog:\n  host: nas\n  severity: verbose\n", "syslog.severity"),
])
def test_syslog_invalid(tmp_path: Path, block: str, match: str) -> None:
    with pytest.raises(ConfigError, match=match):
        _load_with_syslog(tmp_path, block)


# ---------------------------------------------------------------------------
# target_firmware: one version or a list
# ---------------------------------------------------------------------------


def _load_with_firmware(tmp_path: Path, value: str) -> CameraConfig:
    text = VALID_YAML.replace("  - name: legacy-smb\n", f"  - name: legacy-smb\n    target_firmware: {value}\n", 1)
    config_file = tmp_path / "cameras.yaml"
    config_file.write_text(text)
    return load_config(config_file)


def test_target_firmware_list(tmp_path: Path) -> None:
    cfg = _load_with_firmware(tmp_path, '["5.51.7.4", "5.51.7.7"]')
    assert cfg.profiles[0].target_firmware == ["5.51.7.4", "5.51.7.7"]


def test_target_firmware_single_string_becomes_list(tmp_path: Path) -> None:
    assert _load_with_firmware(tmp_path, '"5.51.7.4"').profiles[0].target_firmware == ["5.51.7.4"]


@pytest.mark.parametrize("value", ["5.51", "[5.51, 5.52]", '["5.51.7.4", ""]', "{a: 1}"])
def test_target_firmware_invalid(tmp_path: Path, value: str) -> None:
    # Unquoted 5.51 parses as a float — versions must be strings.
    with pytest.raises(ConfigError, match="target_firmware"):
        _load_with_firmware(tmp_path, value)
