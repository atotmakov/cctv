from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional

from requests.auth import HTTPDigestAuth

from cctv.config import CameraConfig
from cctv.scanner import DiscoveredCamera
from cctv import vapix

# ---------------------------------------------------------------------------
# VAPIX parameter groups — verified on firmware 5.51.7.4 (2026-04-05)
# ---------------------------------------------------------------------------
_SMB_GROUP = "root.NetworkShare"              # VERIFIED on firmware 5.51.7.4
_MOTION_GROUP = "root.Motion"                 # VERIFIED on firmware 5.51.7.4

# SMB parameter names — always targets N0 (primary share slot)
_SMB_HOST = "root.NetworkShare.N0.Address"    # SMB share IP — VERIFIED
_SMB_SHARE = "root.NetworkShare.N0.Share"     # SMB share name (not path) — VERIFIED
_SMB_USER = "root.NetworkShare.N0.Username"   # SMB username — VERIFIED
_SMB_PASS = "root.NetworkShare.N0.Password"   # SMB password — VERIFIED

# Motion parameter names
# NOTE: root.ImageSource.MotionDetection is read-only on this firmware.
# Motion windows are named M0, M1, … — full-frame = Left=0 Right=9999 Top=0 Bottom=9999
_MOTION_SENSITIVITY = "root.Motion.M0.Sensitivity"  # VERIFIED on firmware 5.51.7.4

# Storage parameter names — S1 is the network share (CIFS) slot; S0 is the SD card
_STORAGE_GROUP = "root.Storage"                       # VERIFIED on firmware 5.51.7.4
_STORAGE_RETENTION = "root.Storage.S1.CleanupMaxAge"  # days to retain recordings — VERIFIED

# Hostname parameter names — VERIFIED on firmware 5.51.7.7 (2026-04-16)
_NETWORK_VOLATILE_GROUP = "root.Network.VolatileHostName"          # DHCP-assigned hostname group
_NETWORK_VOLATILE_HOSTNAME = "root.Network.VolatileHostName.HostName"  # hostname from DHCP server
_NETWORK_HOSTNAME = "root.Network.HostName"                        # static hostname (= SMB folder name)

# Full-frame window coordinates (0–9999 normalised coordinate space)
_FULL_FRAME = {"Left": "0", "Right": "9999", "Top": "0", "Bottom": "9999"}


class CameraStatus(Enum):
    APPLIED = "applied"
    NO_CHANGE = "no_change"
    FAILED = "failed"  # set by executor.py — reconcile() never produces this


@dataclass
class CameraResult:
    ip: str
    model: Optional[str]
    status: CameraStatus
    settings_changed: list[str] = field(default_factory=list)
    error: Optional[str] = None  # populated only on FAILED, by executor


def reconcile(
    camera: DiscoveredCamera,
    config: CameraConfig,
    auth: HTTPDigestAuth,
) -> CameraResult:
    """Read current camera state, apply only differing settings.

    Raises VapixError on any network failure — caller (executor.py) is the
    failure-isolation boundary.
    """
    changed: list[str] = []

    # --- SMB settings ---
    smb = vapix.get_params(camera.ip, _SMB_GROUP, auth, config.timeout)

    if smb.get(_SMB_HOST) != config.smb_ip:
        vapix.set_params(camera.ip, {_SMB_HOST: config.smb_ip}, auth, config.timeout)
        changed.append("smb_ip")

    if (
        smb.get(_SMB_SHARE) != config.smb_share
        or smb.get(_SMB_USER) != config.smb_username
        or smb.get(_SMB_PASS) != config.smb_password
    ):
        vapix.set_params(
            camera.ip,
            {
                _SMB_SHARE: config.smb_share,
                _SMB_USER: config.smb_username,
                _SMB_PASS: config.smb_password,
            },
            auth,
            config.timeout,
        )
        changed.append("smb_creds")

    # --- Motion window + sensitivity ---
    # Some cameras ship with a non-full-frame DefaultWindow at M0 (e.g. M3005).
    # We add a full-frame window only when none already exists and root.Motion is
    # non-empty (empty response = camera doesn't expose this group at all).
    motion = vapix.get_params(camera.ip, _MOTION_GROUP, auth, config.timeout)

    if config.motion_enabled:
        window_id = _ensure_motion_window(camera.ip, auth, config.timeout, motion, config)
        if window_id is not None:
            changed.append("motion_window")
            # Re-read motion params after adding the window so the sensitivity
            # check below sees the new entry.
            motion = vapix.get_params(camera.ip, _MOTION_GROUP, auth, config.timeout)

    # Sensitivity — update on whichever full-frame window we own (M0 on most cameras,
    # could be M1+ on cameras that have a pre-existing DefaultWindow at M0).
    full_frame_key = _full_frame_sensitivity_key(motion)
    if full_frame_key is not None:
        desired = str(int(config.motion_sensitivity))
        if motion.get(full_frame_key) != desired:
            vapix.set_params(camera.ip, {full_frame_key: desired}, auth, config.timeout)
            changed.append("motion")

    # --- Storage retention ---
    storage = vapix.get_params(camera.ip, _STORAGE_GROUP, auth, config.timeout)
    retention_str = str(config.recording_retention_days)
    if storage.get(_STORAGE_RETENTION) != retention_str:
        vapix.set_params(
            camera.ip,
            {_STORAGE_RETENTION: retention_str},
            auth,
            config.timeout,
        )
        changed.append("retention")

    # --- Hostname sync: copy DHCP-assigned hostname to static if available ---
    # root.Network.HostName is what the camera uses as the SMB subfolder name.
    # When a DHCP hostname is present, sync it so the folder is human-readable.
    volatile = vapix.get_params(camera.ip, _NETWORK_VOLATILE_GROUP, auth, config.timeout)
    volatile_hostname = volatile.get(_NETWORK_VOLATILE_HOSTNAME, "")
    if volatile_hostname:
        net = vapix.get_params(camera.ip, _NETWORK_HOSTNAME, auth, config.timeout)
        if net.get(_NETWORK_HOSTNAME) != volatile_hostname:
            vapix.set_params(camera.ip, {_NETWORK_HOSTNAME: volatile_hostname}, auth, config.timeout)
            changed.append("hostname")

    # --- Motion detection action rule ---
    if config.motion_enabled:
        # `motion` is already up-to-date (re-read above if a window was just added)
        window_id_for_rule = _find_full_frame_window_id(motion)
        if _ensure_motion_action_rule(camera.ip, auth, config.timeout, window_id_for_rule):
            changed.append("motion_rule")

    status = CameraStatus.APPLIED if changed else CameraStatus.NO_CHANGE
    return CameraResult(
        ip=camera.ip,
        model=camera.model,
        status=status,
        settings_changed=changed,
    )


# ---------------------------------------------------------------------------
# Motion window helpers
# ---------------------------------------------------------------------------

def _parse_motion_windows(motion: dict[str, str]) -> dict[str, dict[str, str]]:
    """Group root.Motion params by window index → {MX: {Left: ..., Right: ..., Name: ...}}."""
    windows: dict[str, dict[str, str]] = {}
    for key, val in motion.items():
        m = re.match(r"root\.Motion\.(M\d+)\.(\w+)$", key)
        if m:
            idx, field = m.groups()
            windows.setdefault(idx, {})[field] = val
    return windows


def _find_full_frame_window_id(motion: dict[str, str]) -> Optional[int]:
    """Return the event-system window ID of the first full-frame motion window, or None."""
    windows = _parse_motion_windows(motion)
    for idx, props in sorted(windows.items()):
        if all(props.get(k) == v for k, v in _FULL_FRAME.items()):
            # MX → window index X in the event system
            return int(idx[1:])
    return None


def _full_frame_sensitivity_key(motion: dict[str, str]) -> Optional[str]:
    """Return the param key for Sensitivity of the first full-frame window, or None."""
    windows = _parse_motion_windows(motion)
    for idx, props in sorted(windows.items()):
        if all(props.get(k) == v for k, v in _FULL_FRAME.items()):
            return f"root.Motion.{idx}.Sensitivity"
    return None


def _ensure_motion_window(
    ip: str,
    auth: HTTPDigestAuth,
    timeout: int,
    motion: dict[str, str],
    config: CameraConfig,
) -> Optional[int]:
    """Add a full-frame motion window if none exists.

    Returns the new window index if created, None if one already existed.
    Skips silently on cameras where root.Motion is not writable (empty response).
    """
    if not motion:
        # Camera does not expose root.Motion (e.g. M3005 without VMD app) — skip
        return None
    if _find_full_frame_window_id(motion) is not None:
        return None  # Already exists
    window_idx = vapix.add_motion_window(ip, auth, timeout, int(config.motion_sensitivity))
    return window_idx


# ---------------------------------------------------------------------------
# Action rule helper
# ---------------------------------------------------------------------------

def _ensure_motion_action_rule(
    ip: str,
    auth: HTTPDigestAuth,
    timeout: int,
    window_id: Optional[int],
) -> bool:
    """Ensure a motion detection → record-to-NetworkShare action rule exists.

    If window_id is provided the rule condition filters on that specific window.
    Returns True if a new rule was created, False if one already exists.
    """
    configs = vapix.get_action_configurations(ip, auth, timeout)
    rules = vapix.get_action_rules(ip, auth, timeout)

    cfg_by_id = {c.config_id: c for c in configs}

    for rule in rules:
        if not rule.enabled:
            continue
        if "MotionDetection" not in rule.topic and "VideoMotionDetection" not in rule.topic:
            continue
        action_cfg = cfg_by_id.get(rule.primary_action)
        if action_cfg and "recording.storage" in action_cfg.template_token:
            if action_cfg.parameters.get("storage_id") == "NetworkShare":
                return False  # Already correctly configured

    # Build message filter
    motion_filter = 'boolean(//SimpleItem[@Name="motion" and @Value="1"])'
    if window_id is not None:
        motion_filter += f' and boolean(//SimpleItem[@Name="window" and @Value="{window_id}"])'

    config_id = vapix.add_action_configuration(
        ip, auth, timeout,
        name="cctv_motion_record",
        template_token="com.axis.action.unlimited.recording.storage",
        parameters={
            "post_duration": "5000",
            "pre_duration": "5000",
            "storage_id": "NetworkShare",
            "stream_options": "",
        },
    )
    vapix.add_action_rule(
        ip, auth, timeout,
        name="cctv_motion_record",
        topic="tns1:VideoAnalytics/tnsaxis:MotionDetection",
        message_filter=motion_filter,
        primary_action=config_id,
    )
    return True
