from __future__ import annotations

import ipaddress
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import yaml


class ConfigError(Exception):
    """Config file missing, unreadable, or schema invalid."""


@dataclass
class SmbStorageConfig:
    ip: str
    share: str
    username: str
    password: str = field(repr=False)


@dataclass
class S3StorageConfig:
    endpoint: str
    region: str
    bucket: str
    access_key: str
    secret_key: str = field(repr=False)


@dataclass
class StorageConfig:
    backend: str  # "smb" | "sd_s3sync"
    smb: Optional[SmbStorageConfig] = None
    sd_s3sync: Optional[S3StorageConfig] = None


SYSLOG_SEVERITIES = ("debug", "info", "notice", "warning", "error", "critical")
_SYSLOG_HOST = re.compile(r"[A-Za-z0-9]([A-Za-z0-9.-]{0,251}[A-Za-z0-9])?")


@dataclass
class SyslogConfig:
    """Remote syslog target — UDP, BSD/RFC3164 format, applied to every camera."""
    host: str
    port: int = 514
    severity: str = "info"  # minimum severity forwarded, one of SYSLOG_SEVERITIES


@dataclass
class Profile:
    """One camera family's desired state — selected per-camera by matching
    `models` against the discovered camera's model string (substring match,
    e.g. "M3085-V" matches "AXIS M3085-V Network Camera")."""
    name: str
    models: list[str]
    target_firmware: list[str]  # accepted versions, [] = unchecked; precondition only — cctv never auto-upgrades firmware
    applications: dict[str, dict]  # e.g. {"video_motion_detection": {"app_package_path": "..."}}
    motion_detection: dict  # shape depends on storage.backend (legacy sensitivity vs VMD4 filters)
    storage: StorageConfig


@dataclass
class CameraConfig:
    subnet: str
    username: str
    password: str = field(repr=False)
    timeout: int = 5
    ntp_fallback_servers: list[str] = field(default_factory=list)
    timezone: Optional[str] = None  # POSIX timezone string, e.g. "CET-1CEST,M3.5.0,M10.5.0/3"
    recording_retention_days: int = 33
    profiles: list[Profile] = field(default_factory=list)
    syslog: Optional[SyslogConfig] = None  # None = leave camera syslog config untouched

    def match_profile(self, model: str) -> Optional[Profile]:
        """Return the first profile whose `models` list matches this camera's
        model string, or None if no profile applies to it."""
        for profile in self.profiles:
            if any(m in model for m in profile.models):
                return profile
        return None


def load_config(path: Path) -> CameraConfig:
    try:
        with path.open() as f:
            data = yaml.safe_load(f)
    except FileNotFoundError:
        raise ConfigError(f"Config file not found: {path}")
    except PermissionError:
        raise ConfigError(f"Config file not readable: {path}")
    except yaml.YAMLError as e:
        raise ConfigError(f"YAML parse error: {e}")

    if not isinstance(data, dict):
        raise ConfigError("Config file is empty or not a YAML mapping")

    for key in ("subnet", "credentials", "profiles"):
        if key not in data:
            raise ConfigError(f"Missing required key: {key}")

    if not isinstance(data["subnet"], str):
        raise ConfigError(
            f"Invalid subnet: must be a string CIDR, got {type(data['subnet']).__name__}"
        )
    try:
        ipaddress.ip_network(data["subnet"], strict=False)
    except ValueError:
        raise ConfigError(f"Invalid subnet: '{data['subnet']}' is not a valid CIDR")

    creds = data["credentials"]
    if not isinstance(creds, dict):
        raise ConfigError("'credentials' must be a YAML mapping, got null or scalar")
    for key in ("username", "password"):
        if key not in creds:
            raise ConfigError(f"Missing required key: credentials.{key}")

    profiles_raw = data["profiles"]
    if not isinstance(profiles_raw, list) or not profiles_raw:
        raise ConfigError("'profiles' must be a non-empty YAML list")
    profiles = [_parse_profile(i, p) for i, p in enumerate(profiles_raw)]

    ntp_fallback_servers = data.get("ntp_fallback_servers") or []
    if not isinstance(ntp_fallback_servers, list):
        raise ConfigError("'ntp_fallback_servers' must be a YAML list of hostnames")

    return CameraConfig(
        subnet=data["subnet"],
        username=creds["username"],
        password=creds["password"],
        timeout=int(_raw) if (_raw := data.get("timeout")) is not None else 5,
        ntp_fallback_servers=list(ntp_fallback_servers),
        timezone=data.get("timezone") or None,
        recording_retention_days=int(_rr) if (_rr := data.get("recording_retention_days")) is not None else 33,
        profiles=profiles,
        syslog=_parse_syslog(data.get("syslog")),
    )


def _parse_syslog(data: object) -> Optional[SyslogConfig]:
    if data is None:
        return None
    if not isinstance(data, dict):
        raise ConfigError("'syslog' must be a YAML mapping")
    host = data.get("host")
    if not isinstance(host, str) or not host:
        raise ConfigError("Missing required key: syslog.host (non-empty string)")
    # Written verbatim into the legacy cameras' /etc/syslog.conf, so anything
    # beyond a plain hostname/IPv4 (spaces, '#', ':', newlines) could break or
    # inject sysklogd rules.
    if not _SYSLOG_HOST.fullmatch(host):
        raise ConfigError(f"syslog.host must be a hostname or IPv4 address, got {host!r}")
    port = data.get("port", 514)
    if isinstance(port, bool) or not isinstance(port, int) or not 1 <= port <= 65535:
        raise ConfigError(f"syslog.port must be an integer 1-65535, got {port!r}")
    severity = data.get("severity", "info")
    if severity not in SYSLOG_SEVERITIES:
        raise ConfigError(
            f"syslog.severity must be one of {', '.join(SYSLOG_SEVERITIES)}, got {severity!r}"
        )
    return SyslogConfig(host=host, port=port, severity=severity)


def _parse_profile(index: int, data: object) -> Profile:
    label = f"profiles[{index}]"
    if not isinstance(data, dict):
        raise ConfigError(f"{label} must be a YAML mapping")

    for key in ("name", "match", "motion_detection", "storage"):
        if key not in data:
            raise ConfigError(f"Missing required key: {label}.{key}")

    name = data["name"]
    if not isinstance(name, str) or not name:
        raise ConfigError(f"{label}.name must be a non-empty string")

    match = data["match"]
    if not isinstance(match, dict) or "models" not in match:
        raise ConfigError(f"{label}.match must be a YAML mapping with a 'models' key")
    models = match["models"]
    if not isinstance(models, list) or not models or not all(isinstance(m, str) for m in models):
        raise ConfigError(f"{label}.match.models must be a non-empty list of strings")

    # One version or a list of accepted versions — a fleet sharing one profile
    # can sit on more than one verified build (e.g. 5.51.7.4 and 5.51.7.7).
    target_firmware_raw = data.get("target_firmware") or []
    if isinstance(target_firmware_raw, str):
        target_firmware_raw = [target_firmware_raw]
    if not isinstance(target_firmware_raw, list) or not all(
        isinstance(v, str) and v for v in target_firmware_raw
    ):
        raise ConfigError(f"{label}.target_firmware must be a version string, a list of them, or omitted")
    target_firmware = list(target_firmware_raw)

    applications_raw = data.get("applications") or {}
    if not isinstance(applications_raw, dict):
        raise ConfigError(f"{label}.applications must be a YAML mapping")
    applications = {k: (v or {}) for k, v in applications_raw.items()}

    motion_detection = data["motion_detection"]
    if not isinstance(motion_detection, dict):
        raise ConfigError(f"{label}.motion_detection must be a YAML mapping")

    storage_raw = data["storage"]
    if not isinstance(storage_raw, dict) or "backend" not in storage_raw:
        raise ConfigError(f"{label}.storage must be a YAML mapping with a 'backend' key")
    backend = storage_raw["backend"]
    if backend not in ("smb", "sd_s3sync"):
        raise ConfigError(f"{label}.storage.backend must be 'smb' or 'sd_s3sync', got {backend!r}")

    smb_cfg: Optional[SmbStorageConfig] = None
    s3_cfg: Optional[S3StorageConfig] = None

    if backend == "smb":
        smb_raw = storage_raw.get("smb")
        if not isinstance(smb_raw, dict):
            raise ConfigError(f"{label}.storage.smb is required when backend is 'smb'")
        for key in ("ip", "share", "username", "password"):
            if key not in smb_raw:
                raise ConfigError(f"Missing required key: {label}.storage.smb.{key}")
        smb_cfg = SmbStorageConfig(
            ip=smb_raw["ip"],
            share=smb_raw["share"],
            username=smb_raw["username"],
            password=smb_raw["password"],
        )
    else:
        s3_raw = storage_raw.get("sd_s3sync")
        if not isinstance(s3_raw, dict):
            raise ConfigError(f"{label}.storage.sd_s3sync is required when backend is 'sd_s3sync'")
        for key in ("endpoint", "region", "bucket", "access_key", "secret_key"):
            if key not in s3_raw:
                raise ConfigError(f"Missing required key: {label}.storage.sd_s3sync.{key}")
        s3_cfg = S3StorageConfig(
            endpoint=s3_raw["endpoint"],
            region=s3_raw["region"],
            bucket=s3_raw["bucket"],
            access_key=s3_raw["access_key"],
            secret_key=s3_raw["secret_key"],
        )

    return Profile(
        name=name,
        models=models,
        target_firmware=target_firmware,
        applications=applications,
        motion_detection=motion_detection,
        storage=StorageConfig(backend=backend, smb=smb_cfg, sd_s3sync=s3_cfg),
    )
