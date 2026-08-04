from __future__ import annotations

import sys

from cctv.reconciler import CameraResult, CameraStatus
from cctv.scanner import DiscoveredCamera
from cctv.status import CameraStatusResult


def print_camera_list(cameras: list[DiscoveredCamera]) -> None:
    """Print per-camera lines and summary count to stdout."""
    for cam in cameras:
        print(f"{cam.ip}  {cam.model}  (reachable)")
    n = len(cameras)
    if n == 0:
        print("No Axis cameras found")
    else:
        noun = "camera" if n == 1 else "cameras"
        print(f"Found {n} Axis {noun}")


def print_apply_results(results: list[CameraResult]) -> int:
    """Print per-camera apply results and summary. Returns exit code (0 or 1)."""
    for result in results:
        if result.status == CameraStatus.APPLIED:
            settings = ", ".join(result.settings_changed)
            print(f"{result.ip}  {result.model}  applied ({settings})")
        elif result.status == CameraStatus.NO_CHANGE:
            print(f"{result.ip}  {result.model}  no change")
        elif result.status == CameraStatus.FAILED:
            print(f"{result.ip}  {result.model}  FAILED — {result.error}")
        else:
            raise ValueError(f"Unexpected CameraStatus: {result.status}")

    n_applied = sum(1 for r in results if r.status == CameraStatus.APPLIED)
    n_no_change = sum(1 for r in results if r.status == CameraStatus.NO_CHANGE)
    n_failed = sum(1 for r in results if r.status == CameraStatus.FAILED)

    summary = f"Summary: {n_applied} applied, {n_no_change} no change, {n_failed} failed"
    if n_failed > 0:
        summary += " — re-run to retry failed cameras"
    print(summary)

    return 1 if n_failed > 0 else 0


def print_camera_status(results: list[CameraStatusResult]) -> int:
    """Print one multi-line block per camera to stdout. Returns exit code (0 or 1)."""
    if not results:
        print("No Axis cameras found")
        return 0

    for result in results:
        if result.error is not None:
            print(f"{result.ip}  {result.model}  STATUS UNAVAILABLE — {result.error}")
            continue

        print(f"{result.ip}  {result.model}")

        if result.motion_app_name:
            version = f" v{result.motion_app_version}" if result.motion_app_version else ""
            source = f" [{result.motion_source}]" if result.motion_source else ""
            print(f"  motion app:   {result.motion_app_name}{version} ({result.motion_app_nice_name}) — {result.motion_app_status}{source}")
        else:
            print("  motion app:   NOT INSTALLED — motion detection requires either the built-in VMD app or a legacy .eap (see motion_detection.app_package_path)")

        if result.motion_enabled:
            window = result.motion_window_detail or "no window configured"
            # A multi-window "windows: ..." detail already carries each window's
            # own sensitivity — the single top-level sensitivity number would
            # just repeat (or misleadingly single out) one of them.
            if result.motion_sensitivity is not None and not window.startswith("windows:"):
                print(f"  motion:       enabled, sensitivity {result.motion_sensitivity}, {window}")
            else:
                print(f"  motion:       enabled, {window}")
        else:
            print("  motion:       no window configured")

        if result.action_rules:
            for rule in result.action_rules:
                state = "" if rule.enabled else " (disabled)"
                pre = f"{rule.pre_duration_ms}ms" if rule.pre_duration_ms is not None else "n/a"
                post = f"{rule.post_duration_ms}ms" if rule.post_duration_ms is not None else "n/a"
                trigger = f" [trigger: {rule.trigger_source}]" if rule.trigger_source else ""
                print(f"  action rules: {rule.name}{state} — {rule.target_template} (pre {pre}, post {post}){trigger}")
        else:
            print("  action rules: none configured")

        if result.motion_rule_mismatch:
            print(f"  motion rule:  MISMATCH — motion app is {result.motion_source} but the recording rule's own trigger is different; run `cctv apply` to migrate it")

        print(f"  smb share:    {result.smb_ip}:{result.smb_share}  (user: {result.smb_username})")
        print(f"  time:         {result.timezone}")
        print(f"  retention:    {result.retention_days} days")
        print()

    n_failed = sum(1 for r in results if r.error is not None)
    return 1 if n_failed > 0 else 0
