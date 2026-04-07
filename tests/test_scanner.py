from unittest.mock import patch

import pytest
from requests.auth import HTTPDigestAuth

from cctv.scanner import DiscoveredCamera, _probe_ip, scan
from cctv.vapix import VapixError

AUTH = HTTPDigestAuth("root", "testpass")
BRAND = {
    "root.Brand.Brand": "AXIS",
    "root.Brand.ProdFullName": "AXIS P3245-V",
    "root.Brand.ProdNbr": "P3245-V",
}
# /30 has 2 usable hosts: .1 and .2
SUBNET_2_HOSTS = "192.168.1.0/30"
# /32 has 1 host
SUBNET_1_HOST = "192.168.1.1/32"


# ---------------------------------------------------------------------------
# scan()
# ---------------------------------------------------------------------------


def test_scan_finds_axis_cameras() -> None:
    with patch("cctv.scanner.get_params", return_value=BRAND):
        result = scan(SUBNET_2_HOSTS, AUTH, timeout=5)
    assert len(result) == 2
    assert all(isinstance(c, DiscoveredCamera) for c in result)
    assert all(c.model == "AXIS P3245-V" for c in result)


def test_scan_skips_non_responding_hosts() -> None:
    with patch("cctv.scanner.get_params", side_effect=VapixError("timeout")):
        result = scan(SUBNET_2_HOSTS, AUTH, timeout=5)
    assert result == []


def test_scan_mixed_results() -> None:
    ips_seen: list[str] = []

    def selective_probe(ip: str, group: str, auth: object, timeout: int) -> dict:
        ips_seen.append(ip)
        if ip.endswith(".1"):
            return BRAND
        raise VapixError("no response")

    with patch("cctv.scanner.get_params", side_effect=selective_probe):
        result = scan(SUBNET_2_HOSTS, AUTH, timeout=5)

    assert len(ips_seen) == 2
    assert len(result) == 1
    assert result[0].ip.endswith(".1")
    assert result[0].model == "AXIS P3245-V"


def test_scan_model_from_brand_response() -> None:
    custom_brand = {**BRAND, "root.Brand.ProdFullName": "AXIS Q6135-LE"}
    with patch("cctv.scanner.get_params", return_value=custom_brand):
        result = scan(SUBNET_1_HOST, AUTH, timeout=5)
    assert len(result) == 1
    assert result[0].model == "AXIS Q6135-LE"


def test_scan_missing_prod_full_name_falls_back_to_unknown() -> None:
    brand_no_model = {"root.Brand.Brand": "AXIS"}
    with patch("cctv.scanner.get_params", return_value=brand_no_model):
        result = scan(SUBNET_1_HOST, AUTH, timeout=5)
    assert len(result) == 1
    assert result[0].model == "Unknown"


# ---------------------------------------------------------------------------
# _probe_ip()
# ---------------------------------------------------------------------------


def test_probe_ip_vapix_error_returns_none() -> None:
    with patch("cctv.scanner.get_params", side_effect=VapixError("timeout")):
        assert _probe_ip("192.168.1.1", AUTH, timeout=5) is None


def test_probe_ip_success_returns_camera() -> None:
    with patch("cctv.scanner.get_params", return_value=BRAND):
        cam = _probe_ip("192.168.1.1", AUTH, timeout=5)
    assert cam == DiscoveredCamera(ip="192.168.1.1", model="AXIS P3245-V")


def test_probe_ip_non_axis_brand_returns_none() -> None:
    """NAS or other device that responds with HTTP 200 but no AXIS brand is filtered out."""
    non_axis = {"http": "5000", "https": "5001"}
    with patch("cctv.scanner.get_params", return_value=non_axis):
        assert _probe_ip("192.168.1.100", AUTH, timeout=5) is None


def test_scan_skips_non_axis_devices() -> None:
    """Devices that return 200 but root.Brand.Brand != AXIS are excluded from results."""
    def probe(ip: str, group: str, auth: object, timeout: int) -> dict:
        if ip.endswith(".1"):
            return BRAND
        return {"http": "5000"}  # NAS-like HTML parse artifact

    with patch("cctv.scanner.get_params", side_effect=probe):
        result = scan(SUBNET_2_HOSTS, AUTH, timeout=5)

    assert len(result) == 1
    assert result[0].ip.endswith(".1")
