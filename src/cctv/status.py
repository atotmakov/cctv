from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from requests.auth import HTTPDigestAuth

from cctv.config import CameraConfig
from cctv.scanner import DiscoveredCamera
from cctv import vapix
from cctv.reconciler import (
    find_vmd_app,
    find_full_frame_window_id,
    full_frame_sensitivity_key,
    parse_motion_windows,
)

# ---------------------------------------------------------------------------
# VAPIX parameter groups — same literal values as reconciler.py (verified there);
# re-declared here because reconciler.py's constants are module-private and this
# is a peer read-only module, not a consumer of reconciler's convergence logic.
# ---------------------------------------------------------------------------
_SMB_GROUP = "root.NetworkShare"
_SMB_HOST = "root.NetworkShare.N0.Address"
_SMB_SHARE = "root.NetworkShare.N0.Share"
_SMB_USER = "root.NetworkShare.N0.Username"

_MOTION_GROUP = "root.Motion"

_STORAGE_GROUP = "root.Storage"
_STORAGE_RETENTION = "root.Storage.S1.CleanupMaxAge"

_TIME_GROUP = "root.Time"
_TIME_TIMEZONE = "root.Time.POSIXTimeZone"

# Same literals as reconciler.py's private constants — re-declared here rather
# than imported, for the same reason as the VAPIX group/param constants above
# (see Story 4.1 Dev Notes: status.py is a peer read-only module, not a consumer
# of reconciler's private convergence internals).
_LEGACY_VMD_APP_NAME = "VideoMotionDetection"
_BUILTIN_MOTION_TOPIC = "tns1:VideoAnalytics/tnsaxis:MotionDetection"
_LEGACY_VMD_APP_MOTION_TOPIC = "tns1:RuleEngine/tnsaxis:VideoMotionDetection/motion"


def _classify_motion_topic(topic: str) -> Optional[str]:
    """Label which event source an action rule's topic actually points at —
    "built-in" / "legacy app (.eap)" / None (not a recognized motion topic,
    e.g. LED control or SFTP-on-storage-failure rules). This is what the rule
    itself is wired to right now, independent of which app is installed (see
    CameraStatusResult.motion_rule_mismatch — installed app and deployed rule
    can disagree if a camera hasn't had `cctv apply` re-run since Story 3.7)."""
    if topic.startswith(_BUILTIN_MOTION_TOPIC):
        return "built-in"
    if topic.startswith(_LEGACY_VMD_APP_MOTION_TOPIC):
        return "legacy app (.eap)"
    return None


def _describe_vmd_app_area(points: list[tuple[float, float]]) -> str:
    """Human-readable size for a legacy VMD app polygon area (normalised -1..1
    coordinate space, same convention as the ONVIF areapolygon event data)."""
    xs = [p[0] for p in points]
    ys = [p[1] for p in points]
    width_pct = round((max(xs) - min(xs)) / 2 * 100)
    height_pct = round((max(ys) - min(ys)) / 2 * 100)
    return f"{width_pct}% x {height_pct}% area"


@dataclass
class ActionRuleStatus:
    name: str
    topic: str
    enabled: bool
    target_template: str
    pre_duration_ms: Optional[str] = None
    post_duration_ms: Optional[str] = None
    trigger_source: Optional[str] = None  # "built-in" / "legacy app (.eap)" / None — FR35/Story 3.7


@dataclass
class CameraStatusResult:
    ip: str
    model: Optional[str]
    motion_app_name: Optional[str] = None
    motion_app_nice_name: Optional[str] = None
    motion_app_status: Optional[str] = None
    motion_app_version: Optional[str] = None
    motion_source: Optional[str] = None  # "legacy app (.eap)" / "built-in" / None (no app) — FR35/Story 3.7
    motion_enabled: bool = False
    motion_sensitivity: Optional[str] = None
    motion_window_present: bool = False
    motion_window_detail: Optional[str] = None  # human-readable window/profile description, or None
    action_rules: list[ActionRuleStatus] = field(default_factory=list)
    # True when an enabled motion-recording rule's own topic disagrees with
    # motion_source (installed app) — i.e. the deployed rule hasn't been
    # migrated to match the currently-installed app (FR35/Story 3.7 finding:
    # `cctv apply` only migrates on re-run, so this can be stale between runs).
    motion_rule_mismatch: bool = False
    smb_ip: Optional[str] = None
    smb_share: Optional[str] = None
    smb_username: Optional[str] = None
    timezone: Optional[str] = None
    retention_days: Optional[str] = None
    error: Optional[str] = None


def collect_status(
    camera: DiscoveredCamera,
    config: CameraConfig,
    auth: HTTPDigestAuth,
) -> CameraStatusResult:
    """Read current camera state via VAPIX. Strictly read-only — never calls a write endpoint.

    Raises VapixError on any network failure — caller (collect_all) is the
    failure-isolation boundary.
    """
    apps = vapix.get_applications(camera.ip, auth, config.timeout)
    app = find_vmd_app(apps)

    # FR35/Story 3.7: which event source actually drives motion on this camera —
    # the legacy 2.2.1 .eap (Story 3.6's install path) or a built-in VMD3/VMD4 app.
    # This determines which action-rule topic reconciler.py wires up (see
    # reconciler._LEGACY_VMD_APP_MOTION_TOPIC / _BUILTIN_MOTION_TOPIC), so it's
    # worth surfacing here too rather than making the operator infer it from the
    # raw package Name.
    if app is None:
        motion_source = None
    elif app.name == _LEGACY_VMD_APP_NAME:
        motion_source = "legacy app (.eap)"
    else:
        motion_source = "built-in"

    motion = vapix.get_params(camera.ip, _MOTION_GROUP, auth, config.timeout)
    sensitivity_key = full_frame_sensitivity_key(motion)
    window_id = find_full_frame_window_id(motion)

    motion_window_present = False
    motion_window_detail: Optional[str] = None
    motion_sensitivity: Optional[str] = None

    if motion_source == "legacy app (.eap)":
        # Real-hardware finding (2026-08-04, 3x AXIS M3005/P1204): the legacy
        # .eap has its OWN polygon detection-area config, entirely separate
        # from root.Motion — read via vaconfig.cgi (see get_vmd_app_config
        # docstring for how this undocumented endpoint was found). All 3 real
        # units tested show an identical factory-default "Detection Area"
        # (~60%x60%, centered) at areaid=0 — this is what the Story 3.7
        # migrated action rule actually triggers on. root.Motion's windows/
        # sensitivity (still real, still written by `cctv apply`'s
        # reconciler — Story 3.1/3.3) describe a DIFFERENT, currently
        # rule-irrelevant surface, so they are deliberately NOT shown here.
        areas = vapix.get_vmd_app_config(camera.ip, auth, config.timeout, app.name)
        if areas:
            motion_window_present = True
            parts = []
            for a in areas:
                desc = _describe_vmd_app_area(a.points)
                # `cctv apply`'s reconciler (Story 3.7 area-expansion step)
                # converges this to exactly 100% x 100% — tag it the same way
                # root.Motion's cctv-managed window is tagged below.
                managed = " (cctv-managed, full-frame)" if desc.startswith("100% x 100%") else ""
                parts.append(f"'{a.name}' {desc}{managed}")
            motion_window_detail = "app area: " + ", ".join(parts)
        # No sensitivity concept in the app's own polygon config (moteConfig
        # is boolean filter flags + an encrypted detection.lua script, not a
        # 0-100 knob) — motion_sensitivity stays None here, deliberately.

    elif motion_source == "built-in":
        motion_window_present = window_id is not None
        motion_window_detail = "full-frame window" if motion_window_present else None

        # A camera's built-in app can also ship a non-full-frame native window
        # (Name="DefaultWindow") alongside a full-frame one `cctv apply` added
        # later (Story 3.1) — list all windows instead of collapsing to one.
        all_windows = parse_motion_windows(motion)
        if len(all_windows) > 1:
            parts = []
            for idx in sorted(all_windows):
                w = all_windows[idx]
                managed = " (cctv-managed, full-frame)" if window_id is not None and int(idx[1:]) == window_id else ""
                parts.append(f"{idx} '{w.get('Name', '')}' sensitivity {w.get('Sensitivity', '?')}{managed}")
            motion_window_detail = "windows: " + " | ".join(parts)

        # Modern built-in VMD3/VMD4 doesn't use root.Motion at all (confirmed
        # empty on real hardware — AXIS_CAMERA_SETUP_MANUAL.md section 1-2) —
        # its window is a profile/include-area, readable via its own JSON API.
        if not motion_window_present:
            profiles = vapix.get_vmd4_profiles(camera.ip, auth, config.timeout)
            if profiles:
                motion_window_present = True
                motion_window_detail = "profile(s): " + ", ".join(p.name or f"#{p.uid}" for p in profiles)

        motion_sensitivity = motion.get(sensitivity_key) if sensitivity_key else None

    configs = vapix.get_action_configurations(camera.ip, auth, config.timeout)
    rules = vapix.get_action_rules(camera.ip, auth, config.timeout)
    cfg_by_id = {c.config_id: c for c in configs}

    action_rules = []
    for rule in rules:
        action_cfg = cfg_by_id.get(rule.primary_action)
        target_template = action_cfg.template_token if action_cfg else "unknown"
        action_rules.append(ActionRuleStatus(
            name=rule.name,
            topic=rule.topic,
            enabled=rule.enabled,
            target_template=target_template,
            pre_duration_ms=action_cfg.parameters.get("pre_duration") if action_cfg else None,
            post_duration_ms=action_cfg.parameters.get("post_duration") if action_cfg else None,
            trigger_source=_classify_motion_topic(rule.topic),
        ))

    # FR35/Story 3.7: flag when a deployed recording rule's own topic doesn't
    # match the currently-installed app — this is exactly the "status looks
    # fine but the rule underneath is still on the wrong topic" gap a plain
    # motion_source label can't surface (`cctv apply` migrates it; until then
    # this stays a stale but silently 'looks configured' rule).
    motion_rule_mismatch = any(
        r.enabled and "recording.storage" in r.target_template
        and r.trigger_source is not None and motion_source is not None
        and r.trigger_source != motion_source
        for r in action_rules
    )

    smb = vapix.get_params(camera.ip, _SMB_GROUP, auth, config.timeout)
    storage = vapix.get_params(camera.ip, _STORAGE_GROUP, auth, config.timeout)
    time = vapix.get_params(camera.ip, _TIME_GROUP, auth, config.timeout)

    # There is no independently readable "enabled" flag on legacy VAPIX (see
    # reconciler.py's D3 note: config.motion_enabled is never written via
    # param.cgi) — a full-frame window's presence is the only observable proxy
    # for "motion detection is set up on this camera", so both fields share it.
    return CameraStatusResult(
        ip=camera.ip,
        model=camera.model,
        motion_app_name=app.name if app else None,
        motion_app_nice_name=app.nice_name if app else None,
        motion_app_status=app.status if app else None,
        motion_app_version=app.version if app else None,
        motion_source=motion_source,
        motion_enabled=motion_window_present,
        motion_sensitivity=motion_sensitivity,
        motion_window_present=motion_window_present,
        motion_window_detail=motion_window_detail,
        action_rules=action_rules,
        motion_rule_mismatch=motion_rule_mismatch,
        smb_ip=smb.get(_SMB_HOST),
        smb_share=smb.get(_SMB_SHARE),
        smb_username=smb.get(_SMB_USER),
        timezone=time.get(_TIME_TIMEZONE),
        retention_days=storage.get(_STORAGE_RETENTION),
    )


def collect_all(
    cameras: list[DiscoveredCamera],
    config: CameraConfig,
    auth: HTTPDigestAuth,
) -> list[CameraStatusResult]:
    """Collect status for every camera. Per-camera failures become error-populated
    results — never raises, mirrors executor.apply_all's failure isolation."""
    results: list[CameraStatusResult] = []
    for camera in cameras:
        try:
            result = collect_status(camera, config, auth)
        except Exception as exc:
            results.append(CameraStatusResult(
                ip=camera.ip,
                model=camera.model,
                error=str(exc),
            ))
        else:
            results.append(result)
    return results
