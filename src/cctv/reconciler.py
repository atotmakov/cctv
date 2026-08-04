from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional

from requests.auth import HTTPDigestAuth

from cctv.config import CameraConfig
from cctv.scanner import DiscoveredCamera
from cctv import vapix
from cctv.vapix import VapixError

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

# Time parameter names — VERIFIED on firmware 5.51.7.7 (2026-04-18)
_TIME_GROUP = "root.Time"
_TIME_TIMEZONE = "root.Time.POSIXTimeZone"   # POSIX timezone string

# Hostname parameter names — VERIFIED on firmware 5.51.7.7 (2026-04-16)
_NETWORK_VOLATILE_GROUP = "root.Network.VolatileHostName"          # DHCP-assigned hostname group
_NETWORK_VOLATILE_HOSTNAME = "root.Network.VolatileHostName.HostName"  # hostname from DHCP server
_NETWORK_HOSTNAME = "root.Network.HostName"                        # static hostname (= SMB folder name)

# Full-frame window coordinates (0–9999 normalised coordinate space)
_FULL_FRAME = {"Left": "0", "Right": "9999", "Top": "0", "Bottom": "9999"}

# The AXIS Video Motion Detection app's internal package Name is NOT constant across
# versions: "vmd" on VMD3/VMD4 (see AXIS_CAMERA_SETUP_MANUAL.md section 1), but
# "VideoMotionDetection" on the older 2.2.1 .eap used for legacy cameras — confirmed
# by installing it on a real AXIS M3005. Match on either, or on NiceName as a fallback.
VMD_APP_NAMES = ("vmd", "VideoMotionDetection")
VMD_NICE_NAME = "AXIS Video Motion Detection"

# The legacy 2.2.1 .eap registers under this package Name specifically (as opposed
# to "vmd", used by the built-in VMD3/VMD4 app pre-installed on modern cameras).
# Used to decide which event topic the motion action rule should target — see
# _BUILTIN_MOTION_TOPIC / _LEGACY_VMD_APP_MOTION_TOPIC below.
_LEGACY_VMD_APP_NAME = "VideoMotionDetection"

# Built-in motion event topic — VERIFIED, pre-existing (Story 3.1).
_BUILTIN_MOTION_TOPIC = "tns1:VideoAnalytics/tnsaxis:MotionDetection"

# VERIFIED on firmware 5.51.7.4 (2026-07-25), Story 3.7/FR35 — event topic published
# by the legacy 2.2.1 .eap once installed (Story 3.6). Confirmed against a real AXIS
# M3005 (192.168.1.60): manually set the cctv_motion_record rule's trigger to
# "Applications > VideoMotionDetection" in the camera's own web UI, then read back
# the resulting topic/filter via GetActionRules — the camera-generated values below,
# not a guess. NOTE: unlike the built-in topic's "window" index (root.Motion.MX,
# read via param.cgi), "areaid" is the app's own polygon-area index — area 0 is the
# app's default/only area on every camera tested (see _ensure_vmd_app_area below,
# which now reads AND writes this via vapix.get_vmd_app_config/set_vmd_app_config).
_LEGACY_VMD_APP_MOTION_TOPIC = "tns1:RuleEngine/tnsaxis:VideoMotionDetection/motion"

# VERIFIED end-to-end against a real AXIS M3005 (192.168.1.60, 2026-08-04): the
# legacy .eap's own factory-default "Detection Area" only covers ~60% of the frame
# (centered) — and this area, not root.Motion, is what the Story 3.7-migrated
# action rule (above) actually triggers on. _ensure_vmd_app_area expands it to
# full-frame to match cctv's full-frame intent, mirroring _ensure_motion_window's
# root.Motion behaviour for built-in cameras. Reuses the app's own existing area
# name so the rule's pre-existing "Include" reference keeps working unchanged.
_LEGACY_VMD_APP_AREA_NAME = "Detection Area"
_LEGACY_VMD_APP_FULL_FRAME_POINTS = [(1.0, 1.0), (1.0, -1.0), (-1.0, -1.0), (-1.0, 1.0)]
_LEGACY_VMD_APP_MOTION_FILTER = 'boolean(//SimpleItem[@Name="active" and @Value="1"]) and boolean(//SimpleItem[@Name="areaid" and @Value="0"])'

# VERIFIED end-to-end against a real AXIS M3085-V (192.168.1.72, firmware
# 12.11.72, 2026-08-04): the built-in VMD3/VMD4 app's default profile ships
# covering only ~97% of the frame (not full) — expand its "includeArea"
# trigger to this. Unlike the legacy app, this is Axis's own official,
# documented JSON control API (local/vmd/control.cgi, method=setConfiguration)
# — see vapix.set_vmd4_configuration for the one undocumented quirk found
# (request payload key is "params", not "data").
_VMD4_FULL_FRAME_AREA = [[-1.0, -1.0], [-1.0, 1.0], [1.0, 1.0], [1.0, -1.0]]


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

    # --- Motion detection app (legacy cameras may not ship with it installed) ---
    vmd_app: Optional[vapix.InstalledApplication] = None
    if config.motion_enabled:
        app_change, vmd_app = _ensure_motion_app_installed(camera.ip, auth, config.timeout, config)
        if app_change is not None:
            changed.append(app_change)

        # The app's own detection area (separate from root.Motion below) ships
        # covering less than the full frame by default — expand to full-frame.
        # Legacy and built-in apps use two entirely different config APIs.
        if vmd_app is not None:
            if vmd_app.name == _LEGACY_VMD_APP_NAME:
                area_change = _ensure_vmd_app_area(camera.ip, auth, config.timeout, vmd_app)
            else:
                area_change = _ensure_vmd4_full_frame_area(camera.ip, auth, config.timeout)
            if area_change is not None:
                changed.append(area_change)

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
    full_frame_key = full_frame_sensitivity_key(motion)
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

    # --- Time settings ---
    if config.timezone:
        time = vapix.get_params(camera.ip, _TIME_GROUP, auth, config.timeout)
        if time.get(_TIME_TIMEZONE) != config.timezone:
            vapix.set_params(camera.ip, {_TIME_TIMEZONE: config.timezone}, auth, config.timeout)
            changed.append("timezone")

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
        window_id_for_rule = find_full_frame_window_id(motion)
        # FR35: on cameras where the legacy VMD app is what provides motion at all
        # (Story 3.6 install path), the rule must trigger off the app's own event,
        # not the built-in window-based topic used everywhere else.
        use_legacy_app_topic = vmd_app is not None and vmd_app.name == _LEGACY_VMD_APP_NAME
        if _ensure_motion_action_rule(
            camera.ip, auth, config.timeout, window_id_for_rule,
            config.motion_pre_trigger_time * 1000,
            config.motion_post_trigger_time * 1000,
            use_legacy_app_topic=use_legacy_app_topic,
        ):
            changed.append("motion_rule")

    status = CameraStatus.APPLIED if changed else CameraStatus.NO_CHANGE
    return CameraResult(
        ip=camera.ip,
        model=camera.model,
        status=status,
        settings_changed=changed,
    )


# ---------------------------------------------------------------------------
# Motion app install helper
# ---------------------------------------------------------------------------

def find_vmd_app(apps: list[vapix.InstalledApplication]) -> Optional[vapix.InstalledApplication]:
    """Find the installed AXIS Video Motion Detection app, whatever its package Name."""
    for a in apps:
        if a.name in VMD_APP_NAMES or a.nice_name == VMD_NICE_NAME:
            return a
    return None


def _ensure_motion_app_installed(
    ip: str,
    auth: HTTPDigestAuth,
    timeout: int,
    config: CameraConfig,
) -> tuple[Optional[str], Optional[vapix.InstalledApplication]]:
    """Ensure the AXIS Video Motion Detection app is installed and running.

    Legacy cameras may not ship with the app pre-installed, so it must be
    uploaded from a local .eap package (motion_detection.app_package_path in
    config) before any motion detection can be configured.

    Only Status="Stopped" triggers a start call (matches AXIS_CAMERA_SETUP_MANUAL.md
    section 2). Other non-Stopped statuses are left alone — confirmed on a real
    AXIS M3005 that the legacy 2.2.1 app settles into Status="Idle" (not "Running")
    once actually started, so treating "anything but Running" as stopped would
    re-issue a start call on every reconcile.

    Returns a (change_label, app) tuple: change_label is "motion_app_installed" /
    "motion_app_started" if an action was taken, None if the app was already
    installed and running. app is the matched InstalledApplication either way
    (used by the caller to pick the right action-rule event topic — FR35).
    """
    apps = vapix.get_applications(ip, auth, timeout)
    app = find_vmd_app(apps)

    if app is None:
        if not config.motion_app_package_path:
            raise VapixError(
                f"AXIS Video Motion Detection app is not installed on {ip} and no "
                "motion_detection.app_package_path is configured to install it from"
            )
        vapix.upload_application(ip, auth, timeout, config.motion_app_package_path)
        # The package Name assigned by the camera isn't known until after install
        # (it varies by .eap version — see VMD_APP_NAMES above), so re-list to find it.
        apps = vapix.get_applications(ip, auth, timeout)
        app = find_vmd_app(apps)
        if app is None:
            raise VapixError(
                f"Uploaded {config.motion_app_package_path} to {ip} but no AXIS Video "
                "Motion Detection app appeared in the installed-applications list afterwards"
            )
        vapix.start_application(ip, auth, timeout, app.name)
        return "motion_app_installed", app

    if app.status == "Stopped":
        vapix.start_application(ip, auth, timeout, app.name)
        return "motion_app_started", app

    return None, app


def _vmd_app_area_is_full_frame(areas: list[vapix.VmdAppArea]) -> bool:
    """True if any configured area already covers (approximately) the full
    -1..1 normalised frame in both axes."""
    for a in areas:
        if not a.points:
            continue
        xs = [p[0] for p in a.points]
        ys = [p[1] for p in a.points]
        if min(xs) <= -0.99 and max(xs) >= 0.99 and min(ys) <= -0.99 and max(ys) >= 0.99:
            return True
    return False


def _ensure_vmd_app_area(
    ip: str,
    auth: HTTPDigestAuth,
    timeout: int,
    app: vapix.InstalledApplication,
) -> Optional[str]:
    """Ensure the legacy VMD app's own detection area covers the full frame.

    Real-hardware finding (2026-08-04): the app's factory-default "Detection
    Area" only covers ~60% of the frame (centered), not root.Motion's
    full-frame window — and this area is what the Story 3.7-migrated action
    rule actually triggers on (root.Motion is a separate, rule-irrelevant
    surface once migrated). Overwrites with a single full-frame polygon under
    the same area name so the pre-existing rule's "Include" reference (which
    targets the area by name) keeps working unchanged.

    Returns "motion_app_area" if a change was made, None if already full-frame.
    """
    areas = vapix.get_vmd_app_config(ip, auth, timeout, app.name)
    if _vmd_app_area_is_full_frame(areas):
        return None
    vapix.set_vmd_app_config(
        ip, auth, timeout, app.name,
        [vapix.VmdAppArea(name=_LEGACY_VMD_APP_AREA_NAME, points=_LEGACY_VMD_APP_FULL_FRAME_POINTS)],
    )
    return "motion_app_area"


def _vmd4_profile_is_full_frame(profile: dict) -> bool:
    """True if the profile's includeArea trigger already covers (approximately)
    the full -1..1 frame. Profiles without an includeArea trigger (e.g. some
    other trigger type) are left alone — not treated as needing a change."""
    for trigger in profile.get("triggers", []):
        if trigger.get("type") != "includeArea":
            continue
        points = trigger.get("data", [])
        if not points:
            continue
        xs = [p[0] for p in points]
        ys = [p[1] for p in points]
        if min(xs) <= -0.99 and max(xs) >= 0.99 and min(ys) <= -0.99 and max(ys) >= 0.99:
            return True
    return False


def _ensure_vmd4_full_frame_area(ip: str, auth: HTTPDigestAuth, timeout: int) -> Optional[str]:
    """Ensure the built-in VMD3/VMD4 app's profile(s) cover the full frame.

    Real-hardware finding (2026-08-04): the app's default profile ships
    covering only ~97% of the frame — not full. Expands each profile's
    includeArea trigger to full-frame in place, preserving everything else
    (filters, uid, name, other trigger types) via a read-modify-write on the
    opaque config dict — mirrors _ensure_vmd_app_area's approach for the
    legacy app, using the official VMD4 API instead of the reverse-engineered
    legacy one.

    Returns "motion_app_area" if any profile was changed, None otherwise
    (including when there are no profiles at all — nothing to configure).
    """
    data = vapix.get_vmd4_configuration(ip, auth, timeout)
    profiles = data.get("profiles", [])
    changed = False
    for profile in profiles:
        if _vmd4_profile_is_full_frame(profile):
            continue
        for trigger in profile.get("triggers", []):
            if trigger.get("type") == "includeArea":
                trigger["data"] = _VMD4_FULL_FRAME_AREA
                changed = True
    if not changed:
        return None
    vapix.set_vmd4_configuration(ip, auth, timeout, data)
    return "motion_app_area"


# ---------------------------------------------------------------------------
# Motion window helpers
# ---------------------------------------------------------------------------

def parse_motion_windows(motion: dict[str, str]) -> dict[str, dict[str, str]]:
    """Group root.Motion params by window index → {MX: {Left: ..., Right: ..., Name: ...}}."""
    windows: dict[str, dict[str, str]] = {}
    for key, val in motion.items():
        m = re.match(r"root\.Motion\.(M\d+)\.(\w+)$", key)
        if m:
            idx, field = m.groups()
            windows.setdefault(idx, {})[field] = val
    return windows


def find_full_frame_window_id(motion: dict[str, str]) -> Optional[int]:
    """Return the event-system window ID of the first full-frame motion window, or None."""
    windows = parse_motion_windows(motion)
    for idx, props in sorted(windows.items()):
        if all(props.get(k) == v for k, v in _FULL_FRAME.items()):
            # MX → window index X in the event system
            return int(idx[1:])
    return None


def full_frame_sensitivity_key(motion: dict[str, str]) -> Optional[str]:
    """Return the param key for Sensitivity of the first full-frame window, or None."""
    windows = parse_motion_windows(motion)
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
    if find_full_frame_window_id(motion) is not None:
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
    pre_duration_ms: int,
    post_duration_ms: int,
    use_legacy_app_topic: bool = False,
) -> bool:
    """Ensure a motion detection → record-to-NetworkShare action rule exists with the correct durations.

    If window_id is provided the rule condition filters on that specific window
    (only meaningful for the built-in topic — the legacy app topic ignores it,
    see FR35 / Story 3.7).
    use_legacy_app_topic selects the legacy VMD app's own event topic instead of
    the built-in window-based topic — set when the camera needed Story 3.6's
    install path to get motion at all.
    Returns True if a rule was created or updated, False if already correctly configured.
    """
    configs = vapix.get_action_configurations(ip, auth, timeout)
    rules = vapix.get_action_rules(ip, auth, timeout)

    cfg_by_id = {c.config_id: c for c in configs}

    # Build topic + message filter first — legacy-app-install cameras (FR35) target
    # the app's own event; everything else keeps the pre-existing built-in window
    # topic. Needed before the existing-rule scan below so a pre-existing rule can
    # be checked against the *currently* desired topic, not just its durations —
    # real-hardware finding (2026-08-03): a rule created before this camera's motion
    # started depending on the legacy app still has matching durations, so without
    # this topic check it would be silently left on the wrong (built-in) topic
    # forever, never migrated by a subsequent `cctv apply` re-run.
    if use_legacy_app_topic:
        topic = _LEGACY_VMD_APP_MOTION_TOPIC
        motion_filter = _LEGACY_VMD_APP_MOTION_FILTER
    else:
        topic = _BUILTIN_MOTION_TOPIC
        motion_filter = 'boolean(//SimpleItem[@Name="motion" and @Value="1"])'
        if window_id is not None:
            motion_filter += f' and boolean(//SimpleItem[@Name="window" and @Value="{window_id}"])'

    for rule in rules:
        if not rule.enabled:
            continue
        if "MotionDetection" not in rule.topic and "VideoMotionDetection" not in rule.topic:
            continue
        action_cfg = cfg_by_id.get(rule.primary_action)
        if action_cfg and "recording.storage" in action_cfg.template_token:
            if action_cfg.parameters.get("storage_id") == "NetworkShare":
                if (rule.topic.startswith(topic) and
                        action_cfg.parameters.get("pre_duration") == str(pre_duration_ms) and
                        action_cfg.parameters.get("post_duration") == str(post_duration_ms)):
                    return False  # Already correctly configured
                # Topic mismatch (built-in vs legacy app) or durations differ — remove and recreate
                vapix.remove_action_rule(ip, auth, timeout, rule.rule_id)
                vapix.remove_action_configuration(ip, auth, timeout, action_cfg.config_id)
                break

    config_id = vapix.add_action_configuration(
        ip, auth, timeout,
        name="cctv_motion_record",
        template_token="com.axis.action.unlimited.recording.storage",
        parameters={
            "pre_duration": str(pre_duration_ms),
            "post_duration": str(post_duration_ms),
            "storage_id": "NetworkShare",
            "stream_options": "",
        },
    )
    vapix.add_action_rule(
        ip, auth, timeout,
        name="cctv_motion_record",
        topic=topic,
        message_filter=motion_filter,
        primary_action=config_id,
    )
    return True
