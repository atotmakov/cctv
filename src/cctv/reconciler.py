from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional

from requests.auth import HTTPDigestAuth

from cctv.config import CameraConfig, Profile, S3StorageConfig, SyslogConfig
from cctv.scanner import DiscoveredCamera
from cctv import vapix
from cctv.vapix import VapixError

# ---------------------------------------------------------------------------
# VAPIX parameter groups — verified on firmware 5.51.7.4 (2026-04-05) for the
# legacy/SMB fleet, firmware 12.11.72 (2026-08-29) for the M3085-V/SD+S3 fleet
# ---------------------------------------------------------------------------
_SMB_GROUP = "root.NetworkShare"
_MOTION_GROUP = "root.Motion"

# Default (and overwhelmingly common) slot. The Nx index is internal parhand
# bookkeeping and is NOT guaranteed to be N0 — see find_network_share_index and
# vapix.get_network_shares. Writes go to the resolved index; these constants are
# the fallback used when a camera has no share configured at all yet.
_SMB_HOST = "root.NetworkShare.N0.Address"
_SMB_SHARE = "root.NetworkShare.N0.Share"
_SMB_USER = "root.NetworkShare.N0.Username"
_SMB_PASS = "root.NetworkShare.N0.Password"

_STORAGE_GROUP = "root.Storage"
_STORAGE_RETENTION_S1 = "root.Storage.S1.CleanupMaxAge"  # NetworkShare (smb backend)
_STORAGE_RETENTION_S0 = "root.Storage.S0.CleanupMaxAge"  # SD_DISK (sd_s3sync backend)

_TIME_GROUP = "root.Time"
_TIME_TIMEZONE = "root.Time.POSIXTimeZone"

_NETWORK_VOLATILE_GROUP = "root.Network.VolatileHostName"
_NETWORK_VOLATILE_HOSTNAME = "root.Network.VolatileHostName.HostName"
_NETWORK_HOSTNAME = "root.Network.HostName"

_FIRMWARE_VERSION = "root.Properties.Firmware.Version"

_SDS3SYNC_GROUP = "root.Sds3sync"
_SDS3SYNC_APP_NAME = "sds3sync"

# Remote syslog. Legacy fleet: one managed forwarding line in sysklogd's
# config, preceded by a marker comment. sysklogd 1.4.1 syntax has no port
# field — "@host" always means UDP 514.
_SYSLOG_CONF_PATH = "/etc/syslog.conf"
_SYSLOG_MARKER = "# cctv: remote syslog"
_SYSLOG_LEGACY_PORT = 514
_SYSLOG_LEGACY_SELECTOR = {"error": "err", "critical": "crit"}  # others are spelled the same
_SYSLOG_REBOOTED_LABEL = "syslog (camera rebooted)"
# AXIS OS 12 remotesyslog.cgi severity spelling (developer.axis.com remote syslog API)
_SYSLOG_API_SEVERITY = {
    "debug": "Debug", "info": "Informational", "notice": "Notice",
    "warning": "Warning", "error": "Error", "critical": "Critical",
}

_FULL_FRAME = {"Left": "0", "Right": "9999", "Top": "0", "Bottom": "9999"}

VMD_APP_NAMES = ("vmd", "VideoMotionDetection")
VMD_NICE_NAME = "AXIS Video Motion Detection"
_LEGACY_VMD_APP_NAME = "VideoMotionDetection"

_BUILTIN_MOTION_TOPIC = "tns1:VideoAnalytics/tnsaxis:MotionDetection"
_LEGACY_VMD_APP_MOTION_TOPIC = "tns1:RuleEngine/tnsaxis:VideoMotionDetection/motion"
_LEGACY_VMD_APP_AREA_NAME = "Detection Area"
_LEGACY_VMD_APP_FULL_FRAME_POINTS = [(1.0, 1.0), (1.0, -1.0), (-1.0, -1.0), (-1.0, 1.0)]
_LEGACY_VMD_APP_MOTION_FILTER = 'boolean(//SimpleItem[@Name="active" and @Value="1"]) and boolean(//SimpleItem[@Name="areaid" and @Value="0"])'

_VMD4_FULL_FRAME_AREA = [[-1.0, -1.0], [-1.0, 1.0], [1.0, 1.0], [1.0, -1.0]]

# sd_to_s3_sync ACAP: constants proven working end-to-end against real hardware
# (2026-08-28/29) — not user-configurable, since they're identical across every
# M3085-V camera (fixed SD mount path, sane sync cadence).
_SDS3SYNC_RECORDING_PATH = "/var/spool/storage/SD_DISK"
_SDS3SYNC_INTERVAL_SECONDS = "60"
_SDS3SYNC_HEARTBEAT_INTERVAL_SECONDS = "300"
_SDS3SYNC_S3_PATH_STYLE = "yes"
_SDS3SYNC_S3_INSECURE_TLS = "no"


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

    Raises VapixError on any network failure, on no profile matching this
    camera's model, or on a target_firmware mismatch — caller (executor.py)
    is the failure-isolation boundary. A firmware mismatch or missing-profile
    error is raised BEFORE any setting is touched, so a camera on the wrong
    firmware or with no matching profile is never partially converged.
    """
    profile = config.match_profile(camera.model or "")
    if profile is None:
        raise VapixError(
            f"No profile in cameras.yaml matches model {camera.model!r} on {camera.ip} — "
            "add a profile whose match.models covers this camera"
        )

    if profile.target_firmware:
        fw = vapix.get_params(camera.ip, _FIRMWARE_VERSION, auth, config.timeout)
        current_fw = fw.get(_FIRMWARE_VERSION)
        if current_fw != profile.target_firmware:
            raise VapixError(
                f"Firmware mismatch on {camera.ip}: profile '{profile.name}' expects "
                f"{profile.target_firmware!r}, camera reports {current_fw!r}. cctv does not "
                "auto-upgrade firmware — upgrade manually, then re-run."
            )

    if config.syslog and profile.storage.backend == "smb" and config.syslog.port != _SYSLOG_LEGACY_PORT:
        raise VapixError(
            f"syslog.port {config.syslog.port} not supported on {camera.ip}: legacy firmware "
            f"(sysklogd 1.4.1) can only forward to UDP port {_SYSLOG_LEGACY_PORT}"
        )

    changed: list[str] = []

    if profile.storage.backend == "smb":
        changed += _reconcile_smb_backend(camera, profile, config, auth)
    else:
        changed += _reconcile_sd_s3sync_backend(camera, profile, config, auth)

    changed += _reconcile_retention(camera, profile, config, auth)

    if config.timezone:
        changed += _reconcile_timezone(camera, config, auth)

    if config.ntp_fallback_servers:
        changed += _reconcile_ntp_fallback(camera, config, auth)

    changed += _reconcile_hostname_sync(camera, config, auth)

    if config.syslog:
        if profile.storage.backend == "smb":
            # Must stay the LAST step: the reboot cuts off any later VAPIX call.
            if _ensure_legacy_syslog_conf(camera.ip, auth, config.timeout, config.syslog):
                try:
                    vapix.restart_camera(camera.ip, auth, config.timeout)
                except VapixError as e:
                    # The file now matches, so a re-run would see nothing to do and
                    # never reboot — the operator has to finish this one by hand.
                    raise VapixError(
                        f"{_SYSLOG_CONF_PATH} updated on {camera.ip} but restart failed ({e}) — "
                        "reboot the camera manually for syslog forwarding to take effect"
                    )
                changed.append(_SYSLOG_REBOOTED_LABEL)
        elif _ensure_remote_syslog_api(camera.ip, auth, config.timeout, config.syslog):
            changed.append("syslog")

    status = CameraStatus.APPLIED if changed else CameraStatus.NO_CHANGE
    return CameraResult(
        ip=camera.ip,
        model=camera.model,
        status=status,
        settings_changed=changed,
    )


# ---------------------------------------------------------------------------
# smb backend (legacy fleet — AXIS OS 5.x)
# ---------------------------------------------------------------------------

def _reconcile_smb_backend(
    camera: DiscoveredCamera,
    profile: Profile,
    config: CameraConfig,
    auth: HTTPDigestAuth,
) -> list[str]:
    changed: list[str] = []
    smb_cfg = profile.storage.smb
    assert smb_cfg is not None  # config.py guarantees this when backend == "smb"

    smb = vapix.get_params(camera.ip, _SMB_GROUP, auth, config.timeout)
    host_key, share_key, user_key, pass_key = smb_param_keys(
        find_network_share_index(smb, smb_cfg.ip, smb_cfg.share)
    )

    if smb.get(host_key) != smb_cfg.ip:
        vapix.set_params(camera.ip, {host_key: smb_cfg.ip}, auth, config.timeout)
        changed.append("smb_ip")

    if (
        smb.get(share_key) != smb_cfg.share
        or smb.get(user_key) != smb_cfg.username
        or smb.get(pass_key) != smb_cfg.password
    ):
        vapix.set_params(
            camera.ip,
            {share_key: smb_cfg.share, user_key: smb_cfg.username, pass_key: smb_cfg.password},
            auth,
            config.timeout,
        )
        changed.append("smb_creds")

    md = profile.motion_detection
    motion_enabled = bool(md.get("enabled", True))

    vmd_app: Optional[vapix.InstalledApplication] = None
    if motion_enabled:
        app_package_path = profile.applications.get("video_motion_detection", {}).get("app_package_path")
        app_change, vmd_app = _ensure_motion_app_installed(camera.ip, auth, config.timeout, app_package_path)
        if app_change is not None:
            changed.append(app_change)

        if vmd_app is not None:
            if vmd_app.name == _LEGACY_VMD_APP_NAME:
                area_change = _ensure_vmd_app_area(camera.ip, auth, config.timeout, vmd_app)
            else:
                area_change = _ensure_vmd4_full_frame_area(camera.ip, auth, config.timeout)
            if area_change is not None:
                changed.append(area_change)

    motion = vapix.get_params(camera.ip, _MOTION_GROUP, auth, config.timeout)

    if motion_enabled:
        window_id = _ensure_motion_window(camera.ip, auth, config.timeout, motion, int(md.get("sensitivity", 50)))
        if window_id is not None:
            changed.append("motion_window")
            motion = vapix.get_params(camera.ip, _MOTION_GROUP, auth, config.timeout)

    full_frame_key = full_frame_sensitivity_key(motion)
    if full_frame_key is not None:
        desired = str(int(md.get("sensitivity", 50)))
        if motion.get(full_frame_key) != desired:
            vapix.set_params(camera.ip, {full_frame_key: desired}, auth, config.timeout)
            changed.append("motion")

    if motion_enabled:
        window_id_for_rule = find_full_frame_window_id(motion)
        use_legacy_app_topic = vmd_app is not None and vmd_app.name == _LEGACY_VMD_APP_NAME

        if use_legacy_app_topic:
            topic = _LEGACY_VMD_APP_MOTION_TOPIC
            message_filter = _LEGACY_VMD_APP_MOTION_FILTER
        else:
            topic = _BUILTIN_MOTION_TOPIC
            message_filter = 'boolean(//SimpleItem[@Name="motion" and @Value="1"])'
            if window_id_for_rule is not None:
                message_filter += f' and boolean(//SimpleItem[@Name="window" and @Value="{window_id_for_rule}"])'

        if _ensure_action_rule(
            camera.ip, auth, config.timeout,
            rule_name="cctv_motion_record",
            storage_id="NetworkShare",
            topic=topic,
            message_filter=message_filter,
            pre_duration_ms=int(md.get("pre_trigger_time", 5)) * 1000,
            post_duration_ms=int(md.get("post_trigger_time", 5)) * 1000,
        ):
            changed.append("motion_rule")

    return changed


# ---------------------------------------------------------------------------
# sd_s3sync backend (M3085-V fleet — AXIS OS 12.x)
# ---------------------------------------------------------------------------

def _reconcile_sd_s3sync_backend(
    camera: DiscoveredCamera,
    profile: Profile,
    config: CameraConfig,
    auth: HTTPDigestAuth,
) -> list[str]:
    changed: list[str] = []
    md = profile.motion_detection
    motion_enabled = bool(md.get("enabled", True))

    if motion_enabled:
        apps = vapix.get_applications(camera.ip, auth, config.timeout)
        vmd_app = find_vmd_app(apps)
        if vmd_app is None:
            raise VapixError(
                f"AXIS Video Motion Detection (VMD4) not found on {camera.ip} — expected "
                "bundled/pre-installed on this model"
            )

        if vmd_app.status == "Stopped":
            vapix.start_application(camera.ip, auth, config.timeout, vmd_app.name)
            changed.append("motion_app_started")

        area_change = _ensure_vmd4_full_frame_area(camera.ip, auth, config.timeout)
        if area_change is not None:
            changed.append(area_change)

        filters_change = _ensure_vmd4_filters(camera.ip, auth, config.timeout, md)
        if filters_change is not None:
            changed.append(filters_change)

    app_cfg = profile.applications.get("sd_to_s3_sync")
    if app_cfg is None:
        raise VapixError(
            f"profile '{profile.name}' uses storage.backend sd_s3sync but has no "
            "applications.sd_to_s3_sync entry"
        )
    s3_cfg = profile.storage.sd_s3sync
    assert s3_cfg is not None  # config.py guarantees this when backend == "sd_s3sync"

    changed += _reconcile_sd_s3sync_app(camera.ip, auth, config.timeout, app_cfg, s3_cfg)

    if motion_enabled:
        profiles = vapix.get_vmd4_profiles(camera.ip, auth, config.timeout)
        profile_uid = profiles[0].uid if profiles else 1
        topic = f"tnsaxis:CameraApplicationPlatform/VMD/Camera1Profile{profile_uid}"
        message_filter = 'boolean(//SimpleItem[@Name="active" and @Value="1"])'

        if _ensure_action_rule(
            camera.ip, auth, config.timeout,
            rule_name="cctv_motion_sd_record",
            storage_id="SD_DISK",
            topic=topic,
            message_filter=message_filter,
            pre_duration_ms=int(md.get("pre_trigger_time", 5)) * 1000,
            post_duration_ms=int(md.get("post_trigger_time", 5)) * 1000,
        ):
            changed.append("motion_rule")

    return changed


def _ensure_vmd4_filters(ip: str, auth: HTTPDigestAuth, timeout: int, md: dict) -> Optional[str]:
    """Converge the built-in VMD4 app's profile filters (sizePercentage,
    timeShortLivedLimit, distanceSwayingObject) to the configured values.
    Only updates filter types already present in the profile (the factory
    default ships all three — confirmed on real M3085-V hardware) rather than
    inventing new filter entries."""
    desired = {
        "sizePercentage": md.get("size_percentage"),
        "timeShortLivedLimit": md.get("time_short_lived_limit"),
        "distanceSwayingObject": md.get("distance_swaying_object"),
    }
    desired = {k: v for k, v in desired.items() if v is not None}
    if not desired:
        return None

    data = vapix.get_vmd4_configuration(ip, auth, timeout)
    changed = False
    for prof in data.get("profiles", []):
        for f in prof.get("filters", []):
            want = desired.get(f.get("type"))
            if want is None:
                continue
            current = f.get("data")
            if (list(current) if isinstance(current, list) else current) != want:
                f["data"] = want
                f["active"] = True
                changed = True

    if not changed:
        return None
    vapix.set_vmd4_configuration(ip, auth, timeout, data)
    return "motion_filters"


def _reconcile_sd_s3sync_app(
    ip: str,
    auth: HTTPDigestAuth,
    timeout: int,
    app_cfg: dict,
    s3_cfg: S3StorageConfig,
) -> list[str]:
    changed: list[str] = []

    apps = vapix.get_applications(ip, auth, timeout)
    app = next((a for a in apps if a.name == _SDS3SYNC_APP_NAME), None)

    if app is None:
        app_package_path = app_cfg.get("app_package_path")
        if not app_package_path:
            raise VapixError(
                f"sd_to_s3_sync app is not installed on {ip} and no "
                "applications.sd_to_s3_sync.app_package_path is configured to install it from"
            )
        vapix.upload_application(ip, auth, timeout, app_package_path)
        changed.append("sd_to_s3_sync_installed")
        apps = vapix.get_applications(ip, auth, timeout)
        app = next((a for a in apps if a.name == _SDS3SYNC_APP_NAME), None)
        if app is None:
            raise VapixError(
                f"Uploaded {app_package_path} to {ip} but no {_SDS3SYNC_APP_NAME} app "
                "appeared in the installed-applications list afterwards"
            )

    config_changed = _ensure_sds3sync_config(ip, auth, timeout, s3_cfg)
    if config_changed:
        changed.append("sd_to_s3_sync_config")

    # Re-read live status — may have changed since the listing above (e.g. right after install).
    apps = vapix.get_applications(ip, auth, timeout)
    app = next((a for a in apps if a.name == _SDS3SYNC_APP_NAME), app)

    # The app only reads its config at startup (real-hardware finding,
    # 2026-08-28: setting root.Sds3sync.* while running leaves it logging
    # "not configured yet" indefinitely) — restart whenever config changed
    # and it was already running; otherwise just start it if it isn't.
    if app.status == "Running" and config_changed:
        vapix.stop_application(ip, auth, timeout, app.name)
        vapix.start_application(ip, auth, timeout, app.name)
        changed.append("sd_to_s3_sync_restarted")
    elif app.status != "Running":
        vapix.start_application(ip, auth, timeout, app.name)
        changed.append("sd_to_s3_sync_started")

    return changed


def _ensure_sds3sync_config(ip: str, auth: HTTPDigestAuth, timeout: int, s3_cfg: S3StorageConfig) -> bool:
    current = vapix.get_params(ip, _SDS3SYNC_GROUP, auth, timeout)
    desired = {
        "root.Sds3sync.S3Endpoint": s3_cfg.endpoint,
        "root.Sds3sync.S3Region": s3_cfg.region,
        "root.Sds3sync.S3Bucket": s3_cfg.bucket,
        "root.Sds3sync.S3AccessKey": s3_cfg.access_key,
        "root.Sds3sync.S3SecretKey": s3_cfg.secret_key,
        "root.Sds3sync.S3PathStyle": _SDS3SYNC_S3_PATH_STYLE,
        "root.Sds3sync.S3InsecureTLS": _SDS3SYNC_S3_INSECURE_TLS,
        "root.Sds3sync.RecordingPath": _SDS3SYNC_RECORDING_PATH,
        "root.Sds3sync.IntervalSeconds": _SDS3SYNC_INTERVAL_SECONDS,
        "root.Sds3sync.HeartbeatIntervalSeconds": _SDS3SYNC_HEARTBEAT_INTERVAL_SECONDS,
        # Prefix is deliberately NOT managed here — the app auto-derives it
        # from the camera's own hostname on first run, giving every camera
        # its own namespace in the shared bucket with no per-camera config.
    }
    diff = {k: v for k, v in desired.items() if current.get(k) != v}
    if not diff:
        return False
    vapix.set_params(ip, diff, auth, timeout)
    return True


# ---------------------------------------------------------------------------
# General reconciliation — applies regardless of storage backend
# ---------------------------------------------------------------------------

def _reconcile_retention(
    camera: DiscoveredCamera,
    profile: Profile,
    config: CameraConfig,
    auth: HTTPDigestAuth,
) -> list[str]:
    # root.Storage.S0 (SD_DISK) and S1 (NetworkShare) share identical
    # CleanupMaxAge semantics (0 = unlimited) — verified on real hardware —
    # so recording_retention_days applies uniformly, just to a different
    # storage group depending on which backend this camera's profile uses.
    param = _STORAGE_RETENTION_S0 if profile.storage.backend == "sd_s3sync" else _STORAGE_RETENTION_S1
    storage = vapix.get_params(camera.ip, _STORAGE_GROUP, auth, config.timeout)
    desired = str(config.recording_retention_days)
    if storage.get(param) != desired:
        vapix.set_params(camera.ip, {param: desired}, auth, config.timeout)
        return ["retention"]
    return []


def _reconcile_timezone(camera: DiscoveredCamera, config: CameraConfig, auth: HTTPDigestAuth) -> list[str]:
    time = vapix.get_params(camera.ip, _TIME_GROUP, auth, config.timeout)
    if time.get(_TIME_TIMEZONE) != config.timezone:
        vapix.set_params(camera.ip, {_TIME_TIMEZONE: config.timezone}, auth, config.timeout)
        return ["timezone"]
    return []


def _reconcile_ntp_fallback(camera: DiscoveredCamera, config: CameraConfig, auth: HTTPDigestAuth) -> list[str]:
    current = vapix.get_ntp_fallback_servers(camera.ip, auth, config.timeout)
    if current == config.ntp_fallback_servers:
        return []
    vapix.set_ntp_fallback_servers(camera.ip, auth, config.timeout, config.ntp_fallback_servers)
    return ["ntp_fallback"]


def _reconcile_hostname_sync(camera: DiscoveredCamera, config: CameraConfig, auth: HTTPDigestAuth) -> list[str]:
    # root.Network.HostName is what determines the SMB subfolder name (smb
    # backend) and the ACAP's auto-derived S3 prefix (sd_s3sync backend) —
    # sync the DHCP-assigned hostname to it when one is present, so either
    # backend's per-camera namespace stays human-readable.
    volatile = vapix.get_params(camera.ip, _NETWORK_VOLATILE_GROUP, auth, config.timeout)
    volatile_hostname = volatile.get(_NETWORK_VOLATILE_HOSTNAME, "")
    if not volatile_hostname:
        return []
    net = vapix.get_params(camera.ip, _NETWORK_HOSTNAME, auth, config.timeout)
    if net.get(_NETWORK_HOSTNAME) != volatile_hostname:
        vapix.set_params(camera.ip, {_NETWORK_HOSTNAME: volatile_hostname}, auth, config.timeout)
        return ["hostname"]
    return []


# ---------------------------------------------------------------------------
# Remote syslog
# ---------------------------------------------------------------------------

def legacy_syslog_line(syslog: SyslogConfig) -> str:
    selector = _SYSLOG_LEGACY_SELECTOR.get(syslog.severity, syslog.severity)
    return f"*.{selector};authpriv.none\t\t\t\t\t@{syslog.host}"


def _forward_target(line: str) -> Optional[str]:
    """The "@host" action of a sysklogd forwarding rule, or None for any other line."""
    fields = line.split()
    if fields and not line.lstrip().startswith("#") and fields[-1].startswith("@"):
        return fields[-1]
    return None


def render_legacy_syslog_conf(current: str, syslog: SyslogConfig) -> Optional[str]:
    """Return the new syslog.conf text, or None if it already forwards as desired.

    The managed line is the forwarding rule right after the marker comment;
    failing that, any rule already targeting @host (a hand-added line) is
    adopted and marked. Every other line is preserved verbatim.
    """
    desired = legacy_syslog_line(syslog)
    lines = current.split("\n")
    if any(line.split() == desired.split() for line in lines):
        return None

    for i, line in enumerate(lines):
        if line.strip() == _SYSLOG_MARKER:
            if i + 1 < len(lines) and _forward_target(lines[i + 1]):
                lines[i + 1] = desired
            else:
                # Marker without its rule (deleted by hand, or marker last in
                # the file) — never overwrite whatever unrelated line follows.
                lines.insert(i + 1, desired)
            return "\n".join(lines)

    for i, line in enumerate(lines):
        if _forward_target(line) == f"@{syslog.host}":
            lines[i:i + 1] = [_SYSLOG_MARKER, desired]
            return "\n".join(lines)

    return current.rstrip("\n") + f"\n\n{_SYSLOG_MARKER}\n{desired}\n"


def _ensure_legacy_syslog_conf(ip: str, auth: HTTPDigestAuth, timeout: int, syslog: SyslogConfig) -> bool:
    """Write the managed forwarding line if needed. Returns True when written —
    the caller must then reboot, since sysklogd only rereads on restart."""
    current = vapix.read_camera_file(ip, auth, timeout, _SYSLOG_CONF_PATH)
    new = render_legacy_syslog_conf(current, syslog)
    if new is None:
        return False
    try:
        vapix.write_camera_file(ip, auth, timeout, _SYSLOG_CONF_PATH, new)
    except VapixError as e:
        # An interrupted POST may still have saved the file; if it did, a re-run
        # sees nothing to do and never reboots.
        raise VapixError(
            f"{_SYSLOG_CONF_PATH} write on {ip} failed ({e}) — the file may still have "
            "changed; if so, reboot the camera manually for syslog forwarding to take effect"
        )
    return True


def remote_syslog_server(syslog: SyslogConfig) -> dict:
    """Server entry for remotesyslog.cgi `setup`, per the Axis remote syslog API docs."""
    return {
        "address": syslog.host,
        "port": syslog.port,
        "protocol": "UDP",
        "syslogFormat": "RFC3164",
        "severity": _SYSLOG_API_SEVERITY[syslog.severity],
        "type": "All",  # documented values Audit|All — never risk forwarding audit logs only
    }


def _server_matches(current: object, desired: dict) -> bool:
    # Compare only the fields we manage — the camera may report extra keys —
    # and loosely: the `setup` readback (type and case of values) is not yet
    # verified on hardware, and a strict compare would reconfigure every run.
    if not isinstance(current, dict):
        return False
    for key, value in desired.items():
        if key not in current:
            if key == "type":
                continue  # optional, and absent from the documented status example
            return False
        if str(current[key]).lower() != str(value).lower():
            return False
    return True


def _ensure_remote_syslog_api(ip: str, auth: HTTPDigestAuth, timeout: int, syslog: SyslogConfig) -> bool:
    desired = remote_syslog_server(syslog)
    current = vapix.get_remote_syslog(ip, auth, timeout)
    servers = current.get("servers") or []
    if not isinstance(servers, list):
        raise VapixError(f"remotesyslog.cgi status on {ip}: unexpected servers {str(servers)[:200]}")
    if current.get("enabled") is True and len(servers) == 1 and _server_matches(servers[0], desired):
        return False
    vapix.set_remote_syslog(ip, auth, timeout, servers=[desired])
    return True


# ---------------------------------------------------------------------------
# Motion app install helper (legacy .eap — smb backend only; VMD4 on the
# sd_s3sync backend is always bundled, never installed from a package)
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
    app_package_path: Optional[str],
) -> tuple[Optional[str], Optional[vapix.InstalledApplication]]:
    """Ensure the AXIS Video Motion Detection app is installed and running.

    Legacy cameras may not ship with the app pre-installed, so it must be
    uploaded from a local .eap package (applications.video_motion_detection.
    app_package_path in the matched profile) before any motion detection can
    be configured.

    Only Status="Stopped" triggers a start call — other non-Stopped statuses
    are left alone (real-hardware finding: the legacy 2.2.1 app settles into
    Status="Idle" once actually started, not "Running", so treating "anything
    but Running" as stopped would re-issue a start call on every reconcile).

    Returns a (change_label, app) tuple: change_label is "motion_app_installed" /
    "motion_app_started" if an action was taken, None if the app was already
    installed and running. app is the matched InstalledApplication either way
    (used by the caller to pick the right action-rule event topic).
    """
    apps = vapix.get_applications(ip, auth, timeout)
    app = find_vmd_app(apps)

    if app is None:
        if not app_package_path:
            raise VapixError(
                f"AXIS Video Motion Detection app is not installed on {ip} and no "
                "applications.video_motion_detection.app_package_path is configured to install it from"
            )
        vapix.upload_application(ip, auth, timeout, app_package_path)
        # The package Name assigned by the camera isn't known until after install
        # (it varies by .eap version), so re-list to find it.
        apps = vapix.get_applications(ip, auth, timeout)
        app = find_vmd_app(apps)
        if app is None:
            raise VapixError(
                f"Uploaded {app_package_path} to {ip} but no AXIS Video "
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

    Real-hardware finding: the app's factory-default "Detection Area" only
    covers ~60% of the frame (centered) — and this area, not root.Motion's
    full-frame window, is what the linked action rule actually triggers on.
    Overwrites with a single full-frame polygon under the same area name so
    the rule's pre-existing "Include" reference keeps working unchanged.

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

    Real-hardware finding: the app's default profile ships covering only
    ~97% of the frame — not full. Expands each profile's includeArea trigger
    to full-frame in place, preserving everything else (filters, uid, name,
    other trigger types) via a read-modify-write on the opaque config dict.

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
# Network share index helpers (smb backend only)
# ---------------------------------------------------------------------------

def find_network_share_index(
    smb: dict[str, str],
    desired_ip: Optional[str] = None,
    desired_share: Optional[str] = None,
) -> str:
    """Resolve which root.NetworkShare.Nx slot holds this camera's share.

    The index is internal parhand bookkeeping, NOT a stable N0 — a camera that has
    had a share added and removed keeps whatever slot it was given. Real hardware
    (2026-09-17): 192.168.1.60 serves its only share from N1 while 192.168.1.79
    serves the identical share from N0, and reading N0 on .60 yields nothing at
    all. Prefers a slot matching the desired host/share, then the lowest
    configured slot; falls back to "N0" when nothing is configured yet (a camera
    that has never had a share — the reconciler then writes N0, matching how the
    camera itself numbers a first share).
    """
    indices = sorted(
        {m.group(1) for k in smb if (m := re.match(r"root\.NetworkShare\.(N\d+)\.", k))},
        key=lambda idx: int(idx[1:]),
    )
    if not indices:
        return "N0"
    if desired_ip is not None or desired_share is not None:
        for idx in indices:
            base = f"{_SMB_GROUP}.{idx}"
            if (
                (desired_ip is None or smb.get(f"{base}.Address") == desired_ip)
                and (desired_share is None or smb.get(f"{base}.Share") == desired_share)
            ):
                return idx
    return indices[0]


def smb_param_keys(index: str) -> tuple[str, str, str, str]:
    """(Address, Share, Username, Password) param keys for a NetworkShare slot."""
    base = f"{_SMB_GROUP}.{index}"
    return f"{base}.Address", f"{base}.Share", f"{base}.Username", f"{base}.Password"


# ---------------------------------------------------------------------------
# Motion window helpers (legacy root.Motion group — smb backend only)
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
    sensitivity: int,
) -> Optional[int]:
    """Add a full-frame motion window if none exists.

    Returns the new window index if created, None if one already existed.
    Skips silently on cameras where root.Motion is not writable (empty response).
    """
    if not motion:
        return None
    if find_full_frame_window_id(motion) is not None:
        return None
    return vapix.add_motion_window(ip, auth, timeout, sensitivity)


# ---------------------------------------------------------------------------
# Action rule helper — shared by both backends, parameterized by rule name /
# storage target / event topic rather than dispatching on backend internally
# ---------------------------------------------------------------------------

def _ensure_action_rule(
    ip: str,
    auth: HTTPDigestAuth,
    timeout: int,
    *,
    rule_name: str,
    storage_id: str,
    topic: str,
    message_filter: str,
    pre_duration_ms: int,
    post_duration_ms: int,
) -> bool:
    """Ensure a motion → record-to-<storage_id> action rule exists, named
    `rule_name`, with the given topic/durations. Returns True if created or
    recreated, False if already correctly configured."""
    configs = vapix.get_action_configurations(ip, auth, timeout)
    rules = vapix.get_action_rules(ip, auth, timeout)
    cfg_by_id = {c.config_id: c for c in configs}

    for rule in rules:
        if not rule.enabled or rule.name != rule_name:
            continue
        action_cfg = cfg_by_id.get(rule.primary_action)
        if action_cfg and "recording.storage" in action_cfg.template_token:
            if action_cfg.parameters.get("storage_id") == storage_id:
                if (
                    rule.topic.startswith(topic)
                    and action_cfg.parameters.get("pre_duration") == str(pre_duration_ms)
                    and action_cfg.parameters.get("post_duration") == str(post_duration_ms)
                ):
                    return False  # already correctly configured
                vapix.remove_action_rule(ip, auth, timeout, rule.rule_id)
                vapix.remove_action_configuration(ip, auth, timeout, action_cfg.config_id)
                break

    config_id = vapix.add_action_configuration(
        ip, auth, timeout,
        name=rule_name,
        template_token="com.axis.action.unlimited.recording.storage",
        parameters={
            "pre_duration": str(pre_duration_ms),
            "post_duration": str(post_duration_ms),
            "storage_id": storage_id,
            "stream_options": "",
        },
    )
    vapix.add_action_rule(
        ip, auth, timeout,
        name=rule_name,
        topic=topic,
        message_filter=message_filter,
        primary_action=config_id,
    )
    return True
