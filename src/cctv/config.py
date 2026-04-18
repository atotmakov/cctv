from __future__ import annotations

import ipaddress
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import yaml


class ConfigError(Exception):
    """Config file missing, unreadable, or schema invalid."""


@dataclass
class CameraConfig:
    subnet: str
    username: str
    password: str = field(repr=False)
    smb_ip: str
    smb_share: str
    smb_username: str
    smb_password: str = field(repr=False)
    motion_enabled: bool
    motion_sensitivity: int
    motion_pre_trigger_time: int = 5   # seconds recorded before the motion event
    motion_post_trigger_time: int = 5  # seconds recorded after the motion event
    recording_retention_days: int = 33
    timeout: int = 5
    timezone: Optional[str] = None   # POSIX timezone string, e.g. "CET-1CEST,M3.5.0,M10.5.0/3"


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

    for key in ("subnet", "credentials", "smb", "motion_detection"):
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

    smb = data["smb"]
    if not isinstance(smb, dict):
        raise ConfigError("'smb' must be a YAML mapping, got null or scalar")
    for key in ("ip", "share", "username", "password"):
        if key not in smb:
            raise ConfigError(f"Missing required key: smb.{key}")

    motion = data["motion_detection"]
    if not isinstance(motion, dict):
        raise ConfigError("'motion_detection' must be a YAML mapping, got null or scalar")
    for key in ("enabled", "sensitivity"):
        if key not in motion:
            raise ConfigError(f"Missing required key: motion_detection.{key}")

    return CameraConfig(
        subnet=data["subnet"],
        username=creds["username"],
        password=creds["password"],
        smb_ip=smb["ip"],
        smb_share=smb["share"],
        smb_username=smb["username"],
        smb_password=smb["password"],
        motion_enabled=bool(motion["enabled"]),
        motion_sensitivity=int(motion["sensitivity"]),
        motion_pre_trigger_time=int(motion.get("pre_trigger_time", 5)),
        motion_post_trigger_time=int(motion.get("post_trigger_time", 5)),
        recording_retention_days=int(_rr) if (_rr := data.get("recording_retention_days")) is not None else 33,
        timeout=int(_raw) if (_raw := data.get("timeout")) is not None else 5,
        timezone=data.get("timezone") or None,
    )
