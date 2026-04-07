from __future__ import annotations

from requests.auth import HTTPDigestAuth

from cctv.config import CameraConfig
from cctv.scanner import DiscoveredCamera
from cctv.reconciler import CameraResult, CameraStatus, reconcile


def apply_all(
    cameras: list[DiscoveredCamera],
    config: CameraConfig,
    auth: HTTPDigestAuth,
) -> list[CameraResult]:
    """Apply config to every camera. Per-camera failures become FAILED results — never raises."""
    results: list[CameraResult] = []
    for camera in cameras:
        try:
            result = reconcile(camera, config, auth)
        except Exception as exc:
            results.append(CameraResult(
                ip=camera.ip,
                model=camera.model,
                status=CameraStatus.FAILED,
                error=str(exc),
            ))
        else:
            results.append(result)
    return results
