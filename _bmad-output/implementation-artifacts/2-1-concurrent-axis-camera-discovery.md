# Story 2.1: Concurrent Axis Camera Discovery

Status: done

## Story

As a home sysadmin,
I want `cctv list` to scan my subnet and identify all Axis cameras,
So that I know which devices are reachable before running apply.

## Acceptance Criteria

1. **Given** a configured subnet (e.g. `192.168.1.0/24`), **when** I run `cctv list`, **then** every IP in the range is probed concurrently via HTTP, **and** hosts that respond to the VAPIX brand probe are identified as Axis cameras, **and** the scan completes within 30 seconds on a /24 subnet under normal conditions.

2. **Given** a host does not respond within the configured timeout (default 5s), **when** the scanner probes that IP, **then** that IP is silently skipped (not listed, not errored), **and** the scan continues to remaining IPs without blocking.

## Tasks / Subtasks

- [x] Create `src/cctv/scanner.py` — concurrent subnet scanner (AC: 1, 2)
  - [x] Define `DiscoveredCamera` dataclass: `ip: str`, `model: str`
  - [x] Implement `_probe_ip(ip, auth, timeout) -> DiscoveredCamera | None` (private helper)
    - [x] Call `vapix.get_params(ip, "root.Brand", auth, timeout)` to identify Axis camera
    - [x] On success: extract `model = brand.get("root.Brand.ProdFullName", "Unknown")` → return `DiscoveredCamera(ip=ip, model=model)`
    - [x] On `VapixError`: return `None` (host unreachable, non-Axis, or timeout — all silently skipped)
  - [x] Implement `scan(subnet, auth, timeout) -> list[DiscoveredCamera]`
    - [x] Build host list: `[str(h) for h in ipaddress.ip_network(subnet, strict=False).hosts()]`
    - [x] Use `ThreadPoolExecutor(max_workers=min(50, len(hosts)))` from `concurrent.futures`
    - [x] Map `_probe_ip` over all hosts concurrently via `executor.map`
    - [x] Filter out `None` results → return `list[DiscoveredCamera]`
  - [x] **FORBIDDEN:** `import requests` in this file — use `from cctv.vapix import VapixError, get_params`
  - [x] **FORBIDDEN:** `print()` or `sys.stdout.write()` in this file
- [x] Wire `list_cameras` command in `src/cctv/cli.py` (AC: 1, 2)
  - [x] Import `scanner` from `cctv`
  - [x] Import `HTTPDigestAuth` from `requests.auth`
  - [x] Add `config: Path` argument to `list_cameras` with `exists=True, file_okay=True, dir_okay=False, readable=True`
  - [x] Wrap `load_config(config)` in `try/except ConfigError as e:` → `typer.echo(f"Error: {e}", err=True)` + `raise typer.Exit(code=2)`
  - [x] Call `scanner.scan(effective_subnet, auth, cfg.timeout)` and echo camera count placeholder
- [x] Create `tests/test_scanner.py` — unit tests with mocked `vapix.get_params` (AC: 1, 2)
  - [x] `test_scan_finds_axis_cameras` — mock returns brand dict → assert 2 `DiscoveredCamera` returned
  - [x] `test_scan_skips_non_responding_hosts` — mock raises `VapixError` → assert empty list
  - [x] `test_scan_mixed_results` — selective mock → assert only responding IPs in result
  - [x] `test_scan_model_from_brand_response` — verify `model` from `root.Brand.ProdFullName`
  - [x] `test_scan_missing_prod_full_name_falls_back_to_unknown` — missing key → `"Unknown"`
  - [x] `test_probe_ip_vapix_error_returns_none` — `VapixError` → `None`
  - [x] `test_probe_ip_success_returns_camera` — success → `DiscoveredCamera`
- [x] Run `pytest` — all tests pass, no regressions

## Dev Notes

### Files to Create / Modify

- `src/cctv/scanner.py` — **CREATE** (new file)
- `tests/test_scanner.py` — **CREATE** (new file)
- `src/cctv/cli.py` — **MODIFY** (wire `list_cameras`, add `config` arg)

### Module Boundary — CRITICAL

- `scanner.py` must **NOT** `import requests`. It calls `vapix.get_params` and `vapix.VapixError` only.
- `scanner.py` must **NOT** contain `print()` or `sys.stdout.write()`.
- `from requests.auth import HTTPDigestAuth` IS allowed in `scanner.py` (auth is a data object, not an HTTP call).
- `src/cctv/__init__.py` remains **EMPTY**.

### Implementation Pattern

```python
# src/cctv/scanner.py
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
        results = pool.map(lambda ip: _probe_ip(ip, auth, timeout), hosts)
    return [r for r in results if r is not None]


def _probe_ip(ip: str, auth: HTTPDigestAuth, timeout: int) -> DiscoveredCamera | None:
    """Probe a single IP. Returns DiscoveredCamera if Axis camera found, None otherwise."""
    try:
        brand = get_params(ip, "root.Brand", auth, timeout)
        model = brand.get("root.Brand.ProdFullName", "Unknown")
        return DiscoveredCamera(ip=ip, model=model)
    except VapixError:
        return None
```

**Important ThreadPoolExecutor note:** `pool.map` with a `lambda` works fine in Python 3.11. If the lambda causes pickling issues (it won't — threads not processes), use `functools.partial` or `executor.submit` loop instead.

### `cli.py` Changes

`list_cameras` currently raises `NotImplementedError`. Replace with:

```python
@app.command(name="list")
def list_cameras(
    config: Path = typer.Argument(
        ...,
        exists=True,
        file_okay=True,
        dir_okay=False,
        readable=True,
        help="Path to cameras.yaml config file",
    ),
    subnet: Optional[str] = typer.Option(
        None, "--subnet", help="Override subnet (CIDR)", callback=_validate_subnet
    ),
) -> None:
    """Discover Axis cameras on the subnet."""
    try:
        cfg = load_config(config)
    except ConfigError as e:
        typer.echo(f"Error: {e}", err=True)
        raise typer.Exit(code=2)
    auth = HTTPDigestAuth(cfg.username, cfg.password)
    effective_subnet = subnet or cfg.subnet
    cameras = scanner.scan(effective_subnet, auth, cfg.timeout)
    typer.echo(f"Found {len(cameras)} Axis camera(s)")  # placeholder; Story 2.2 owns full output
```

**Note:** Story 2.2 will replace the placeholder `typer.echo` with full formatted output. This story just needs the scan to work end-to-end without `NotImplementedError`.

### Test Patterns

**Patch target:** `cctv.scanner.get_params` (patched at the import site in scanner.py)

```python
from unittest.mock import MagicMock, patch
from requests.auth import HTTPDigestAuth
from cctv.scanner import DiscoveredCamera, _probe_ip, scan
from cctv.vapix import VapixError

AUTH = HTTPDigestAuth("root", "testpass")
BRAND = {
    "root.Brand.Brand": "AXIS",
    "root.Brand.ProdFullName": "AXIS P3245-V",
    "root.Brand.ProdNbr": "P3245-V",
}

def test_scan_finds_axis_cameras():
    with patch("cctv.scanner.get_params", return_value=BRAND):
        result = scan("192.168.1.0/30", AUTH, timeout=5)
    # /30 has 2 hosts: .1 and .2
    assert len(result) == 2
    assert all(isinstance(c, DiscoveredCamera) for c in result)
    assert result[0].model == "AXIS P3245-V"

def test_scan_skips_non_responding_hosts():
    with patch("cctv.scanner.get_params", side_effect=VapixError("timeout")):
        result = scan("192.168.1.0/30", AUTH, timeout=5)
    assert result == []

def test_probe_ip_vapix_error_returns_none():
    with patch("cctv.scanner.get_params", side_effect=VapixError("timeout")):
        assert _probe_ip("192.168.1.1", AUTH, timeout=5) is None

def test_probe_ip_success_returns_camera():
    with patch("cctv.scanner.get_params", return_value=BRAND):
        cam = _probe_ip("192.168.1.1", AUTH, timeout=5)
    assert cam == DiscoveredCamera(ip="192.168.1.1", model="AXIS P3245-V")
```

**Subnet sizes for tests:** Use small subnets to keep tests fast:
- `/30` → 2 hosts (.1, .2)
- `/32` → 0 hosts (use for empty-result test — `/32` has no `.hosts()`)
- `/31` → 0 hosts in strict mode, 2 in `strict=False`... actually `/32` has 1 host in `hosts()` — use a host address like `192.168.1.1/32` → `hosts()` returns `[IPv4Address('192.168.1.1')]`, 1 host.

Wait — `ipaddress.ip_network("192.168.1.1/32", strict=False).hosts()` returns an empty iterator for /32 in Python. Actually no: for a /32, `hosts()` returns the single host address. Let me verify: `ip_network("192.168.1.5/32").hosts()` returns `[IPv4Address('192.168.1.5')]`. And `ip_network("192.168.1.0/30", strict=False).hosts()` returns `.1` and `.2` (the two usable hosts of a /30).

For "empty subnet" test, use a network-only address like `/32` that has no hosts... actually that's tricky. Just use `/30` (2 hosts) for normal tests. The "returns []" case is tested via all-VapixError scenario.

### Architecture Constraints

- `DiscoveredCamera` is defined in `scanner.py` — do NOT define it in `vapix.py` or any other module.
- `CameraResult` / `CameraStatus` will be defined in `executor.py` (Story 3.4) — do NOT create them here.
- `VapixError` is imported from `cctv.vapix` — do NOT redefine it.
- Story 2.2 owns: formatted per-camera output lines, summary count line, exit code 2 when no cameras found. This story only needs a placeholder output line.
- `ThreadPoolExecutor` is stdlib (`concurrent.futures`) — no new dependency.
- `ipaddress` is stdlib — no new dependency.

### Previous Story Learnings (from Stories 1.1–1.4)

- **`from __future__ import annotations`** at top of every new module.
- **`@dataclass`** with `from dataclasses import dataclass` — no `field(repr=False)` needed here (no secrets in `DiscoveredCamera`).
- **`from requests.auth import HTTPDigestAuth`** is allowed outside `vapix.py` — only `import requests` (the HTTP client) is restricted.
- **Patch target is the import site:** `patch("cctv.scanner.get_params")` not `patch("cctv.vapix.get_params")` — because scanner imports `get_params` into its namespace.
- **venv path on Windows:** `.venv/Scripts/python -m pytest` — use for all test runs.
- **`typer.Exit(code=2)`** not `sys.exit(2)` — Typer-idiomatic.
- **`typer.echo(f"Error: {e}", err=True)`** for stderr in `cli.py` — never `print()`.
- **`exists=True, file_okay=True, dir_okay=False, readable=True`** on all `typer.Argument` Path params.
- **`_validate_subnet` callback** already in `cli.py` — reuse it on `--subnet` option in `list_cameras`.
- **No `import requests` in scanner.py** — the architecture enforces this strictly.

### References

- [architecture.md#Concurrency Model] — `ThreadPoolExecutor`, `max_workers=50`
- [architecture.md#VAPIX API Protocol] — brand probe via `root.Brand` group
- [architecture.md#Gap Analysis] — `DiscoveredCamera` dataclass definition location (scanner.py)
- [architecture.md#Module Responsibility Boundaries] — scanner owns concurrency, not VAPIX protocol
- [epics.md#Story 2.1] — acceptance criteria
- [prd.md#NFR1] — /24 scan in <30s

## Dev Agent Record

### Agent Model Used

claude-sonnet-4-6

### Debug Log References

- No issues encountered. All tasks completed on first attempt.

### Completion Notes List

- `src/cctv/scanner.py`: created with `DiscoveredCamera` dataclass, `scan()` (ThreadPoolExecutor, max_workers=min(50,n)), `_probe_ip()` (probes `root.Brand`, catches VapixError → None); no `import requests`, no `print()`
- `src/cctv/cli.py`: `list_cameras` now accepts `config: Path` arg, loads config, constructs `HTTPDigestAuth`, calls `scanner.scan()`, echoes placeholder count; `apply` unchanged
- `tests/test_scanner.py`: 7 tests — finds cameras, skips non-responding, mixed results, model from ProdFullName, Unknown fallback, _probe_ip direct tests
- 37 pytest tests pass (5 CLI + 10 config + 7 scanner + 15 vapix), 0 failures, 0 regressions

### File List

- src/cctv/scanner.py
- tests/test_scanner.py
- src/cctv/cli.py
