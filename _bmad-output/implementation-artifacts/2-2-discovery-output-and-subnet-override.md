# Story 2.2: Discovery Output and `--subnet` Override

Status: done

## Story

As a home sysadmin,
I want to see a clear list of discovered cameras with their IPs and models, and optionally override the subnet,
So that I can quickly verify my fleet's reachability from the command line.

## Acceptance Criteria

1. **Given** Axis cameras are discovered on the subnet, **when** `cctv list` completes, **then** output shows one line per camera with IP and model (e.g. `192.168.1.101  AXIS P3245-V  (reachable)`), **and** a count of discovered cameras is shown (e.g. `Found 4 Axis cameras`), **and** no configuration changes are made to any camera.

2. **Given** I pass `--subnet 10.0.0.0/24`, **when** `cctv list --subnet 10.0.0.0/24` runs, **then** the scan uses `10.0.0.0/24` instead of the subnet in the config file.

3. **Given** no Axis cameras are found on the subnet, **when** `cctv list` completes, **then** the output states no cameras were found, **and** the process exits with code 2.

## Tasks / Subtasks

- [x] Create `src/cctv/reporter.py` — list output formatter (AC: 1, 3)
  - [x] Import `DiscoveredCamera` from `cctv.scanner`
  - [x] Implement `print_camera_list(cameras: list[DiscoveredCamera]) -> None`
    - [x] For each camera: `print(f"{cam.ip}  {cam.model}  (reachable)")`
    - [x] If `len(cameras) == 0`: `print("No Axis cameras found")`
    - [x] Else: `print(f"Found {n} Axis {'camera' if n == 1 else 'cameras'}")` after per-camera lines
  - [x] **FORBIDDEN:** `import requests` in this file
  - [x] **FORBIDDEN:** `import typer` in this file — reporter knows nothing about the CLI framework
- [x] Modify `src/cctv/cli.py` — replace placeholder echo with reporter call + exit code (AC: 1, 2, 3)
  - [x] Add `from cctv import reporter` import
  - [x] Replace `typer.echo(f"Found {len(cameras)} Axis camera(s)")` with `reporter.print_camera_list(cameras)`
  - [x] After reporter call: `if not cameras: raise typer.Exit(code=2)`
  - [x] **DO NOT** change the `--subnet` option wiring — it already exists with `_validate_subnet` callback
  - [x] **DO NOT** change `apply` command — leave `raise NotImplementedError` as-is
- [x] Create `tests/test_reporter.py` — unit tests for `print_camera_list` (AC: 1, 3)
  - [x] `test_print_camera_list_single_camera` — one camera → correct per-camera line + "Found 1 Axis camera" (singular)
  - [x] `test_print_camera_list_multiple_cameras` — two cameras → two lines + "Found 2 Axis cameras" (plural)
  - [x] `test_print_camera_list_empty` — empty list → "No Axis cameras found", no per-camera lines
  - [x] `test_print_camera_list_format` — verify line contains IP, model, and "(reachable)"
  - [x] Use `capsys` pytest fixture to capture stdout; assert on `capsys.readouterr().out`
- [x] Modify `tests/test_cli.py` — add integration tests for list output (AC: 1, 2, 3)
  - [x] Define `VALID_CONFIG` constant (multi-line YAML string with all required keys) at module top
  - [x] `test_list_cameras_outputs_per_camera_lines` — mock `scanner.scan` returning one camera → assert IP + model in output, exit 0
  - [x] `test_list_cameras_shows_count` — mock returns cameras → "Found N Axis camera" in output
  - [x] `test_list_cameras_exits_2_when_no_cameras` — mock returns `[]` → exit code 2, "No Axis cameras found" in output
  - [x] `test_list_cameras_subnet_override` — invoke with `--subnet 10.0.0.0/24`, mock `scanner.scan` → assert `mock_scan.call_args[0][0] == "10.0.0.0/24"`
- [x] Run `pytest` — all tests pass, no regressions

## Dev Notes

### Files to Create / Modify

- `src/cctv/reporter.py` — **CREATE** (new file)
- `tests/test_reporter.py` — **CREATE** (new file)
- `src/cctv/cli.py` — **MODIFY** (replace placeholder, add reporter import + exit code)
- `tests/test_cli.py` — **MODIFY** (add list integration tests)

### Module Boundary — CRITICAL

- `reporter.py` must use `print()` for all output — this is the designated output module per architecture
- `reporter.py` must **NOT** `import typer` or `import requests`
- `cli.py` continues using `typer.echo(f"Error: {e}", err=True)` for `ConfigError` only — that's the Typer-idiomatic stderr pattern, and is not subject to the reporter.py boundary rule
- `scanner.py` — **DO NOT MODIFY** — all scanner logic is complete and correct from Story 2.1
- `src/cctv/__init__.py` — remains **EMPTY**

### Implementation Pattern

```python
# src/cctv/reporter.py
from __future__ import annotations

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
```

```python
# src/cctv/cli.py — list_cameras changes only
from cctv import reporter  # add this import

@app.command(name="list")
def list_cameras(...) -> None:
    """Discover Axis cameras on the subnet."""
    try:
        cfg = load_config(config)
    except ConfigError as e:
        typer.echo(f"Error: {e}", err=True)
        raise typer.Exit(code=2)
    auth = HTTPDigestAuth(cfg.username, cfg.password)
    effective_subnet = subnet or cfg.subnet
    cameras = scanner.scan(effective_subnet, auth, cfg.timeout)
    reporter.print_camera_list(cameras)          # replaces placeholder typer.echo
    if not cameras:
        raise typer.Exit(code=2)
```

### Test Patterns

**reporter tests (capsys):**
```python
from cctv.scanner import DiscoveredCamera
from cctv.reporter import print_camera_list

def test_print_camera_list_single_camera(capsys):
    print_camera_list([DiscoveredCamera(ip="192.168.1.1", model="AXIS P3245-V")])
    out = capsys.readouterr().out
    assert "192.168.1.1" in out
    assert "AXIS P3245-V" in out
    assert "(reachable)" in out
    assert "Found 1 Axis camera\n" in out   # singular

def test_print_camera_list_empty(capsys):
    print_camera_list([])
    out = capsys.readouterr().out
    assert "No Axis cameras found" in out
    assert "(reachable)" not in out
```

**cli integration tests — VALID_CONFIG and patch target:**
```python
from unittest.mock import patch
from cctv.scanner import DiscoveredCamera

VALID_CONFIG = """\
subnet: 192.168.1.0/24
timeout: 5
credentials:
  username: root
  password: pass
smb:
  ip: 192.168.1.10
  share: /recordings
  username: smbuser
  password: smbpass
motion_detection:
  enabled: true
  sensitivity: 50
"""

def test_list_cameras_exits_2_when_no_cameras(tmp_path):
    cfg = tmp_path / "cameras.yaml"
    cfg.write_text(VALID_CONFIG)
    with patch("cctv.cli.scanner.scan", return_value=[]):
        result = runner.invoke(app, ["list", str(cfg)])
    assert result.exit_code == 2
    assert "No Axis cameras found" in result.output

def test_list_cameras_subnet_override(tmp_path):
    cfg = tmp_path / "cameras.yaml"
    cfg.write_text(VALID_CONFIG)
    with patch("cctv.cli.scanner.scan", return_value=[]) as mock_scan:
        runner.invoke(app, ["list", str(cfg), "--subnet", "10.0.0.0/24"])
    mock_scan.assert_called_once()
    assert mock_scan.call_args[0][0] == "10.0.0.0/24"
```

**Patch target for cli tests:** `cctv.cli.scanner.scan` — because `cli.py` imports `scanner` as a module (`from cctv import scanner`) and calls `scanner.scan(...)`.

### Architecture Constraints

- **`reporter.py` is the print boundary** — all stdout lines for `cctv list` must come from `reporter.py` via `print()`. This is the first module in `reporter.py`; Epic 3 will extend it for `apply` output.
- **Exit code 2 stays in `cli.py`** — `raise typer.Exit(code=2)` is Typer-idiomatic; `reporter.py` does not call `sys.exit()` directly (that would bypass Typer's cleanup). The architecture's `sys.exit()` rule maps to `typer.Exit(code=N)` in this project.
- **`--subnet` option is already wired** — Story 2.1 added `subnet: Optional[str]` with `callback=_validate_subnet`. Do NOT re-add or duplicate it.
- **`apply` stub untouched** — `raise NotImplementedError` stays; Story 3.x owns that.
- **No new dependencies** — `reporter.py` uses stdlib `print()` only.

### Previous Story Learnings (from Stories 1.1–2.1)

- **`from __future__ import annotations`** at top of every new module.
- **`capsys`** is the correct pytest fixture for capturing `print()` output in unit tests.
- **`typer.testing.CliRunner`** captures both stdout and `typer.echo()` output in `result.output`.
- **`typer.echo(f"Error: {e}", err=True)`** goes to stderr and appears in `result.stderr` (not `result.output`) when `mix_stderr=False` on the runner; with default runner settings it appears in `result.output`. Do NOT change existing error echo patterns.
- **Patch target is the import site:** `cctv.cli.scanner.scan` not `cctv.scanner.scan` — because `cli.py` imports `scanner` module, not the function directly.
- **venv path on Windows:** `.venv/Scripts/python -m pytest` for all test runs.
- **`typer.Exit(code=2)`** not `sys.exit(2)`.
- **`exists=True, file_okay=True, dir_okay=False, readable=True`** on `typer.Argument` Path params — already present, do NOT change.
- **`src/cctv/__init__.py` remains EMPTY** — no re-exports.

### VALID_CONFIG for Tests

All CLI tests that invoke `cctv list` with a real config file need all required keys. Missing any of `subnet`, `credentials`, `smb`, `motion_detection` will produce a `ConfigError` and exit 2 before scanning. Use the `VALID_CONFIG` constant defined in the test patterns above.

### References

- [epics.md#Story 2.2] — acceptance criteria, FR2, FR3, FR27
- [architecture.md#Module Responsibility Boundaries] — `reporter.py` owns print/stdout; `cli.py` owns Typer wiring
- [architecture.md#stdout/stderr discipline] — status to stdout, errors to stderr
- [2-1-concurrent-axis-camera-discovery.md] — scanner.py and cli.py patterns established in Story 2.1

## Dev Agent Record

### Agent Model Used

claude-sonnet-4-6

### Debug Log References

- No issues encountered. All tasks completed on first attempt.

### Completion Notes List

- `src/cctv/reporter.py`: created with `print_camera_list(cameras)` — per-camera `IP  model  (reachable)` lines; singular/plural summary ("Found N Axis camera/cameras"); "No Axis cameras found" on empty; no `import requests`, no `import typer`
- `src/cctv/cli.py`: added `from cctv import reporter`; replaced placeholder `typer.echo(f"Found ...")` with `reporter.print_camera_list(cameras)` + `raise typer.Exit(code=2)` when no cameras; `apply` unchanged
- `tests/test_reporter.py`: 4 tests — single camera (singular), multiple cameras (plural), empty list, format check; all use `capsys`
- `tests/test_cli.py`: added `VALID_CONFIG` constant + 4 integration tests — per-camera output, count, exit 2 on empty, subnet override via mock
- 45 pytest tests pass (9 CLI + 10 config + 4 reporter + 7 scanner + 15 vapix), 0 failures, 0 regressions

### File List

- src/cctv/reporter.py
- tests/test_reporter.py
- src/cctv/cli.py
- tests/test_cli.py

### Review Findings

- [x] [Review][Patch] Missing `result.exit_code` assertion in `test_list_cameras_subnet_override` [tests/test_cli.py:101]

- [x] [Review][Defer] `apply` raises bare `NotImplementedError`, producing Python traceback instead of clean error [cli.py:72] — deferred, pre-existing stub (Story 1.1)
- [x] [Review][Defer] Exit code 2 used for both `ConfigError` and no-cameras-found — conflated failure modes [cli.py:43,47] — deferred, pre-existing from Story 1.3
- [x] [Review][Defer] No try/except around `scanner.scan` in `list_cameras` — scan exceptions propagate uncaught [cli.py:45] — deferred, pre-existing
- [x] [Review][Defer] `effective_subnet or cfg.subnet` silently accepts empty-string subnet from config [cli.py:44] — deferred, config.py gap from Story 1.2
- [x] [Review][Defer] Plaintext password passed to `HTTPDigestAuth` with no masking or redaction [cli.py:43] — deferred, pre-existing architectural decision
- [x] [Review][Defer] No integration test for invalid `--subnet` CIDR via CLI [tests/test_cli.py] — deferred, `_validate_subnet` pre-existing from Story 2.1
- [x] [Review][Defer] No test covering AC1 "no configuration changes" constraint [tests/test_cli.py] — deferred, integration-level concern beyond unit test scope
- [x] [Review][Defer] Config.py gaps: `motion_sensitivity` range not validated, `password: null` accepted, empty-string credentials accepted, `timeout` not validated positive [config.py] — deferred, pre-existing from Stories 1.2/1.3
- [x] [Review][Defer] `apply` silently discards `load_config` return value [cli.py:67] — deferred, intentional stub (Story 1.1)
