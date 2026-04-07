from __future__ import annotations

import sys

from cctv.reconciler import CameraResult, CameraStatus
from cctv.scanner import DiscoveredCamera


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
