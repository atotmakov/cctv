from __future__ import annotations

import pytest
from unittest.mock import patch

from cctv.executor import apply_all
from cctv.reconciler import CameraResult, CameraStatus
from cctv.scanner import DiscoveredCamera
from cctv.vapix import VapixError

CAM1 = DiscoveredCamera(ip="192.168.1.101", model="AXIS P3245-V")
CAM2 = DiscoveredCamera(ip="192.168.1.102", model="AXIS P3245-V")
CAM3 = DiscoveredCamera(ip="192.168.1.103", model="AXIS P3245-V")


def _applied(cam: DiscoveredCamera) -> CameraResult:
    return CameraResult(ip=cam.ip, model=cam.model, status=CameraStatus.APPLIED, settings_changed=["smb_ip"])


def test_apply_all_all_succeed(camera_config, mock_auth) -> None:
    applied1 = _applied(CAM1)
    applied2 = _applied(CAM2)
    with patch("cctv.executor.reconcile", side_effect=[applied1, applied2]) as mock_rec:
        results = apply_all([CAM1, CAM2], camera_config, mock_auth)
    assert len(results) == 2
    assert results[0].status == CameraStatus.APPLIED
    assert results[1].status == CameraStatus.APPLIED
    assert mock_rec.call_count == 2


def test_apply_all_one_fails_others_continue(camera_config, mock_auth) -> None:
    applied1 = _applied(CAM1)
    applied3 = _applied(CAM3)
    with patch("cctv.executor.reconcile", side_effect=[applied1, VapixError("timeout"), applied3]):
        results = apply_all([CAM1, CAM2, CAM3], camera_config, mock_auth)
    assert len(results) == 3
    assert results[0].status == CameraStatus.APPLIED
    assert results[1].status == CameraStatus.FAILED
    assert results[1].error  # error field must be populated on FAILED result
    assert results[2].status == CameraStatus.APPLIED


def test_apply_all_failed_result_has_correct_ip_model_status(camera_config, mock_auth) -> None:
    with patch("cctv.executor.reconcile", side_effect=VapixError("error")):
        results = apply_all([CAM1], camera_config, mock_auth)
    assert results[0].ip == CAM1.ip
    assert results[0].model == CAM1.model
    assert results[0].status == CameraStatus.FAILED


def test_apply_all_error_contains_reason_not_credentials(camera_config, mock_auth) -> None:
    error_msg = f"Connection timeout to {CAM1.ip}"
    with patch("cctv.executor.reconcile", side_effect=VapixError(error_msg)):
        results = apply_all([CAM1], camera_config, mock_auth)
    assert "timeout" in results[0].error
    assert camera_config.password not in results[0].error
    assert camera_config.smb_password not in results[0].error
    assert camera_config.username not in results[0].error
    assert camera_config.smb_username not in results[0].error


def test_apply_all_empty_fleet_returns_empty_list(camera_config, mock_auth) -> None:
    with patch("cctv.executor.reconcile") as mock_rec:
        results = apply_all([], camera_config, mock_auth)
    assert results == []
    mock_rec.assert_not_called()


def test_apply_all_no_change_passthrough(camera_config, mock_auth) -> None:
    no_change = CameraResult(ip=CAM1.ip, model=CAM1.model, status=CameraStatus.NO_CHANGE, settings_changed=[])
    with patch("cctv.executor.reconcile", return_value=no_change):
        results = apply_all([CAM1], camera_config, mock_auth)
    assert len(results) == 1
    assert results[0].status == CameraStatus.NO_CHANGE


def test_apply_all_non_vapix_exception_also_caught(camera_config, mock_auth) -> None:
    with patch("cctv.executor.reconcile", side_effect=Exception("unexpected error")):
        results = apply_all([CAM1], camera_config, mock_auth)
    assert results[0].status == CameraStatus.FAILED
    assert results[0].error == "unexpected error"
