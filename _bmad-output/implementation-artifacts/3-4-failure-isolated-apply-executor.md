# Story 3.4: Failure-Isolated Apply Executor

Status: done

## Story

As a home sysadmin,
I want one offline or failing camera to not abort the run for other cameras,
So that a partial fleet is still configured when I have a temporarily unreachable device.

## Acceptance Criteria

1. **Given** one camera is unreachable (connection timeout), **when** `cctv apply` runs across a 4-camera fleet, **then** the remaining 3 cameras are fully configured **and** the failed camera produces a `CameraResult` with `status=FAILED` and an error message **and** the error message includes the camera IP and reason.

2. **Given** a camera returns a VAPIX error during apply, **when** the executor processes that camera, **then** the exception is caught and converted to `CameraResult(status=FAILED, error=...)` **and** camera credentials are never included in the `error` field.

## Tasks / Subtasks

- [x] Create `src/cctv/executor.py` (AC: 1, 2)
  - [x] `from __future__ import annotations` at module top
  - [x] Import `HTTPDigestAuth` from `requests.auth`; import `CameraConfig` from `cctv.config`; import `DiscoveredCamera` from `cctv.scanner`; import `CameraResult, CameraStatus, reconcile` from `cctv.reconciler`
  - [x] Define `apply_all(cameras: list[DiscoveredCamera], config: CameraConfig, auth: HTTPDigestAuth) -> list[CameraResult]`
    - [x] Iterate cameras sequentially; for each call `reconcile(camera, config, auth)`
    - [x] Wrap each reconcile call in `try/except Exception as exc:` — append `CameraResult(ip=camera.ip, model=camera.model, status=CameraStatus.FAILED, error=str(exc))` on failure
    - [x] Append successful `CameraResult` from `reconcile()` on success
    - [x] Return full `results` list — **never raises**
  - [x] **DO NOT** call `print()` — reporter.py owns all output
  - [x] **DO NOT** `import requests` — all network is in vapix.py
  - [x] **DO NOT** call `reporter.py` here — Story 3.5 wires reporting
- [x] Create `tests/test_executor.py` (AC: 1, 2)
  - [x] `test_apply_all_all_succeed` — 2 cameras, both reconcile returns APPLIED → results list has 2 APPLIED entries, reconcile called twice (AC: 1)
  - [x] `test_apply_all_one_fails_others_continue` — 3 cameras, second raises `VapixError` → first and third are APPLIED, second is FAILED, all 3 appear in results (AC: 1)
  - [x] `test_apply_all_failed_result_has_correct_ip_model_status` — camera raises → result has `ip=camera.ip`, `model=camera.model`, `status=CameraStatus.FAILED` (AC: 1)
  - [x] `test_apply_all_error_contains_reason_not_credentials` — `VapixError("Connection timeout to 192.168.1.101")` raised → `"timeout"` in `result.error`, `camera_config.password` NOT in `result.error`, `camera_config.smb_password` NOT in `result.error` (AC: 1, 2)
  - [x] `test_apply_all_empty_fleet_returns_empty_list` — empty cameras list → empty results list, reconcile never called
  - [x] `test_apply_all_non_vapix_exception_also_caught` — camera raises bare `Exception("unexpected error")` → result is FAILED with `error="unexpected error"` (AC: 2 — catch all, not just VapixError)
- [x] Modify `src/cctv/cli.py` — wire `apply` command
  - [x] Add `from cctv import executor` to imports (alongside existing `reporter, scanner`)
  - [x] Replace `raise NotImplementedError` with full apply body:
    - [x] Build `auth = HTTPDigestAuth(cfg.username, cfg.password)`
    - [x] Compute `effective_subnet = subnet or cfg.subnet`
    - [x] Call `cameras = scanner.scan(effective_subnet, auth, cfg.timeout)`
    - [x] Call `results = executor.apply_all(cameras, cfg, auth)`
    - [x] No output yet — Story 3.5 adds `reporter.print_apply_results(results)`
    - [x] No per-result exit code yet — Story 3.5 handles exit codes; for now exit 0
  - [x] Store `cfg` (not just `load_config` return value) — the current stub only validates but discards cfg
- [x] Update `tests/test_cli.py` — apply command no longer raises `NotImplementedError`
  - [x] Add `test_apply_runs_executor` — valid config + mock scanner returns 2 cameras + mock executor.apply_all returns results → apply exits 0
  - [x] Verify `test_apply_invalid_config` still exits 2 (ConfigError path unchanged)
- [x] Run `pytest` — all tests pass, no regressions

## Dev Notes

### executor.py — Full Implementation

```python
# src/cctv/executor.py
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
```

**Why catch `Exception` (not just `VapixError`):** The architecture mandates executor is the failure-isolation boundary. Any unexpected exception (encoding error, memory error from a library, etc.) must not abort the fleet loop. VapixError is the expected failure type but broad catch is intentional.

**Why `str(exc)` for error:** VapixError messages are constructed as `f"Connection timeout to {ip}"` — no credentials ever appear in VapixError. `str(exc)` is safe per NFR7 as long as reconcile.py and vapix.py follow the no-credentials-in-errors rule (enforced throughout).

### cli.py — apply Command After This Story

```python
@app.command()
def apply(
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
    """Apply config to all discovered cameras."""
    try:
        cfg = load_config(config)
    except ConfigError as e:
        typer.echo(f"Error: {e}", err=True)
        raise typer.Exit(code=2)
    auth = HTTPDigestAuth(cfg.username, cfg.password)
    effective_subnet = subnet or cfg.subnet
    cameras = scanner.scan(effective_subnet, auth, cfg.timeout)
    results = executor.apply_all(cameras, cfg, auth)
    # reporter.print_apply_results(results)  — Story 3.5
```

Add `from cctv import executor` to the existing imports block alongside `reporter, scanner`.

**Note:** The current stub loads config and discards it (variable never used). Replace the full stub body, not just `raise NotImplementedError`.

### Patch Targets for test_executor.py

`executor.py` imports reconcile directly:
```python
from cctv.reconciler import CameraResult, CameraStatus, reconcile
```

Patch at the **import site** in executor:
```python
patch("cctv.executor.reconcile")  # NOT "cctv.reconciler.reconcile"
```

### test_executor.py — Full Patterns

```python
from __future__ import annotations

import pytest
from unittest.mock import patch, MagicMock, call

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


def test_apply_all_empty_fleet_returns_empty_list(camera_config, mock_auth) -> None:
    with patch("cctv.executor.reconcile") as mock_rec:
        results = apply_all([], camera_config, mock_auth)
    assert results == []
    mock_rec.assert_not_called()


def test_apply_all_non_vapix_exception_also_caught(camera_config, mock_auth) -> None:
    with patch("cctv.executor.reconcile", side_effect=Exception("unexpected error")):
        results = apply_all([CAM1], camera_config, mock_auth)
    assert results[0].status == CameraStatus.FAILED
    assert results[0].error == "unexpected error"
```

### test_cli.py — New apply Test

```python
def test_apply_runs_executor(tmp_path: Path) -> None:
    cfg = tmp_path / "cameras.yaml"
    cfg.write_text(VALID_CONFIG)
    cameras = [DiscoveredCamera(ip="192.168.1.101", model="AXIS P3245-V")]
    from cctv.reconciler import CameraResult, CameraStatus
    results = [CameraResult(ip="192.168.1.101", model="AXIS P3245-V", status=CameraStatus.APPLIED, settings_changed=["smb_ip"])]
    with patch("cctv.cli.scanner.scan", return_value=cameras), \
         patch("cctv.cli.executor.apply_all", return_value=results) as mock_exec:
        result = runner.invoke(app, ["apply", str(cfg)])
    assert result.exit_code == 0
    mock_exec.assert_called_once()
```

Note: patch `cctv.cli.executor.apply_all` — cli.py imports executor as module (`from cctv import executor`), so patch at the cli import site.

### Architecture Constraints — CRITICAL

- **`import requests` FORBIDDEN** in executor.py — all network is in vapix.py
- **`print()` FORBIDDEN** in executor.py — reporter.py owns all output (Story 3.5)
- **`reporter.py` DO NOT CALL** from executor.py — Story 3.5 adds reporter integration
- **`config.timeout` always** — executor passes config to reconcile which uses it
- **`src/cctv/__init__.py` remains EMPTY**
- **Catch `Exception`, not just `VapixError`** — executor is the full failure isolation boundary
- **Never include credentials in `error` field** — `str(VapixError)` is safe; `str(exc)` from any exception should not include passwords (reconcile.py enforces this)
- **Sequential processing** — no concurrency in executor (NFR2 allows 60s for ≤10 cameras)

### Import Pattern in cli.py

Follow existing module import style:
```python
# BEFORE (current):
from cctv import reporter, scanner

# AFTER (this story):
from cctv import executor, reporter, scanner
```

### Module Call Graph (after this story)

```
cli.py
  ├── config.py      (load + validate)
  ├── scanner.py     (discover cameras)
  └── executor.py    (apply loop)
        └── reconciler.py
              └── vapix.py
```

`reporter.py` not yet called from executor — wired in Story 3.5.

### What reporter.py Already Has (DO NOT ADD apply output here)

`reporter.py` currently only has `print_camera_list()` for the `list` command. Story 3.5 will add `print_apply_results(results: list[CameraResult])`. Do NOT add apply-specific output in this story.

### Previous Story Learnings (Stories 1.1–3.3)

- `from __future__ import annotations` at top of every new module
- `from cctv import vapix` / `from cctv import executor` — module-level imports for correct patch targets
- `field(default_factory=list)` for mutable dataclass defaults — already set in CameraResult
- **venv path on Windows:** `.venv/Scripts/python -m pytest`
- Patch at import site: `cctv.executor.reconcile` not `cctv.reconciler.reconcile`
- `{**fixture, key: val}` copy pattern — never mutate fixture dicts
- `mock_set.assert_not_called()` for explicit no-call assertions

### Files to Create / Modify

- `src/cctv/executor.py` — **CREATE**
- `tests/test_executor.py` — **CREATE**
- `src/cctv/cli.py` — **MODIFY** (wire apply command, add executor import)
- `tests/test_cli.py` — **MODIFY** (add test_apply_runs_executor)
- `src/cctv/reporter.py` — **DO NOT TOUCH**

### References

- [epics.md#Story 3.4] — acceptance criteria, FR12, FR15
- [architecture.md#Error Handling & Result Model] — CameraResult, executor failure isolation boundary
- [architecture.md#Module Responsibility Boundaries] — executor owns orchestration, not output or protocol
- [3-1-read-before-write-state-reconciliation.md] — reconcile() signature and VapixError propagation

## Dev Agent Record

### Agent Model Used

claude-sonnet-4-6

### Debug Log References

- No issues encountered. All tasks completed on first attempt.

### Completion Notes List

- `src/cctv/executor.py`: created `apply_all()` — sequential per-camera loop with `try/except Exception`; successful results appended from `reconcile()`, failures appended as `CameraResult(status=FAILED, error=str(exc))`; no `print()`, no `import requests`, no reporter calls; never raises
- `tests/test_executor.py`: 6 tests — `test_apply_all_all_succeed` (AC1: 2 cameras both APPLIED, reconcile called twice), `test_apply_all_one_fails_others_continue` (AC1: 3 cameras, second raises VapixError → APPLIED/FAILED/APPLIED), `test_apply_all_failed_result_has_correct_ip_model_status` (AC1: ip/model/status on FAILED result), `test_apply_all_error_contains_reason_not_credentials` (AC2: timeout in error, passwords not in error), `test_apply_all_empty_fleet_returns_empty_list` (empty list → empty, reconcile not called), `test_apply_all_non_vapix_exception_also_caught` (AC2: bare Exception caught, FAILED with error text); patch target `cctv.executor.reconcile`
- `src/cctv/cli.py`: added `executor` to `from cctv import executor, reporter, scanner`; replaced full apply stub — `cfg = load_config(config)`, builds auth, calls scanner.scan and executor.apply_all; reporter call commented for Story 3.5
- `tests/test_cli.py`: added `test_apply_runs_executor` — mocks scanner.scan and executor.apply_all, asserts exit 0 and apply_all called once; patch target `cctv.cli.executor.apply_all`
- 67 pytest tests pass (10 CLI + 10 config + 6 executor + 15 reconciler + 4 reporter + 7 scanner + 15 vapix), 0 failures, 0 regressions

### File List

- src/cctv/executor.py
- tests/test_executor.py
- src/cctv/cli.py
- tests/test_cli.py

### Review Findings

- [x] [Review][Patch] `test_apply_all_one_fails_others_continue` missing error field assertion [tests/test_executor.py:37] — assert `results[1].error` is non-empty; FAILED result with no error field would be invisible
- [x] [Review][Patch] `test_apply_all_error_contains_reason_not_credentials` missing username checks [tests/test_executor.py:50] — AC2 says "credentials never in error"; test checks password/smb_password but not username/smb_username
- [x] [Review][Patch] `test_apply_runs_executor` does not assert executor call arguments [tests/test_cli.py:110] — `assert_called_once()` only checks count; wrong cameras/cfg/auth would pass silently
- [x] [Review][Patch] Remove unused imports `MagicMock, call` from test_executor.py [tests/test_executor.py:4]
- [x] [Review][Patch] Add `test_apply_all_no_change_passthrough` test [tests/test_executor.py] — `NO_CHANGE` status from reconcile is untested; `apply_all` could accidentally overwrite it
- [x] [Review][Patch] Move inline import to module level in test_cli.py [tests/test_cli.py:104] — `from cctv.reconciler import CameraResult, CameraStatus` inside test body hides ImportError until runtime
- [x] [Review][Defer] `apply` exits 0 even when all cameras FAILED [src/cctv/cli.py:75] — intentional per story spec; Story 3.5 owns exit codes
- [x] [Review][Defer] `apply` produces no output (reporter commented out) [src/cctv/cli.py:75] — intentional per story spec; Story 3.5 adds reporter.print_apply_results
- [x] [Review][Defer] `str(exc)` may leak credentials from non-VapixError exceptions [src/cctv/executor.py:22] — architectural enforcement at vapix.py/reconciler.py boundary; broad catch is intentional per spec
- [x] [Review][Defer] Credentials test uses manually crafted VapixError message [tests/test_executor.py:44] — pre-existing pattern per spec; structural protection at vapix.py ensures real errors are safe
- [x] [Review][Defer] `apply --subnet` override path untested [tests/test_cli.py] — out of Story 3.4 scope; equivalent test exists for `list` command
- [x] [Review][Defer] `reconcile` partial-apply atomicity — pre-existing, covered in deferred-work.md from Story 3.1
- [x] [Review][Defer] `_parse_param_response` empty-value silent drop — pre-existing, covered in deferred-work.md from Story 1.4
- [x] [Review][Defer] `DiscoveredCamera.model` vs `CameraResult.model` Optional typing mismatch — pre-existing
- [x] [Review][Defer] AC1 spec says 4-camera fleet, test uses 3 — behavior covered; cardinality in spec is illustrative, not prescriptive
