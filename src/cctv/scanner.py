from __future__ import annotations

import ipaddress
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass

from requests.auth import HTTPDigestAuth

from cctv.vapix import VapixError, get_params


@dataclass
class DiscoveredCamera:
    ip: str
    model: str


def scan(subnet: str, auth: HTTPDigestAuth, timeout: int) -> list[DiscoveredCamera]:
    """Probe every IP in subnet concurrently. Returns only reachable Axis cameras."""
    hosts = [str(h) for h in ipaddress.ip_network(subnet, strict=False).hosts()]
    if not hosts:
        return []
    with ThreadPoolExecutor(max_workers=min(50, len(hosts))) as pool:
        results = list(pool.map(lambda ip: _probe_ip(ip, auth, timeout), hosts))
    return [r for r in results if r is not None]


def _probe_ip(ip: str, auth: HTTPDigestAuth, timeout: int) -> DiscoveredCamera | None:
    """Probe a single IP. Returns DiscoveredCamera if Axis camera found, None otherwise."""
    try:
        brand = get_params(ip, "root.Brand", auth, timeout)
        if brand.get("root.Brand.Brand") != "AXIS":
            return None
        model = brand.get("root.Brand.ProdFullName", "Unknown")
        return DiscoveredCamera(ip=ip, model=model)
    except VapixError:
        return None
