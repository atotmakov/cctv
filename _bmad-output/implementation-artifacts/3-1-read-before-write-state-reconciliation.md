# Story 3.1: Read-Before-Write State Reconciliation

Status: done

## Story

As a home sysadmin,
I want the tool to check each camera's current settings before applying changes,
So that cameras already at the desired state are never modified unnecessarily.

## Acceptance Criteria

1. **Given** a camera whose SMB IP already matches the config, **when** `reconciler.py` compares desired vs actual state, **then** `smb_ip` is not included in the change plan, **and** no SET call is made for that parameter.

2. **Given** a camera whose motion sensitivity differs from the config, **when** `reconciler.py` compares desired vs actual state, **then** `motion_sensitivity` is included in the change plan, **and** `set_params` is called only for parameters that differ.

3. **Given** all three managed settings already match the desired state, **when** reconciliation runs for that camera, **then** no VAPIX SET calls are made, **and** the camera produces a `CameraResult` with status `NO_CHANGE`.

## Tasks / Subtasks

- [x] Create `src/cctv/reconciler.py` — define dataclasses and `reconcile()` function
  - [x] Define `CameraStatus(Enum)` with values `APPLIED = "applied"`, `NO_CHANGE = "no_change"`, `FAILED = "failed"`
  - [x] Define `CameraResult` dataclass: `ip: str`, `model: Optional[str]`, `status: CameraStatus`, `settings_changed: list[str]`, `error: Optional[str] = None`
  - [x] Declare VAPIX param name constants at module top — all marked `# UNVERIFIED` (see Dev Notes)
  - [x] Implement `reconcile(camera: DiscoveredCamera, config: CameraConfig, auth: HTTPDigestAuth) -> CameraResult`
    - [x] GET SMB params via `vapix.get_params(camera.ip, _SMB_GROUP, auth, config.timeout)`
    - [x] Compare each SMB field to config; call `set_params` only for differing values; append label to `changed`
    - [x] GET motion params via `vapix.get_params(camera.ip, _MOTION_GROUP, auth, config.timeout)`
    - [x] Compare each motion field to config; call `set_params` only for differing values; append `"motion"` to `changed` at most once
    - [x] Return `CameraResult(ip=camera.ip, model=camera.model, status=APPLIED if changed else NO_CHANGE, settings_changed=changed)`
  - [x] **DO NOT** catch `VapixError` — let it propagate (executor.py handles it in Story 3.4)
  - [x] **DO NOT** `import requests` — use `from cctv import vapix` module import
  - [x] **DO NOT** call `print()` — reporter.py owns all output
  - [x] Always use `config.timeout` — never hardcode a timeout value
- [x] Update `tests/conftest.py` — add VAPIX response fixtures for reconciler tests
  - [x] Add `smb_params_response() -> dict[str, str]` fixture — returns dict matching `_SMB_GROUP` params for the default `camera_config`
  - [x] Add `motion_params_response() -> dict[str, str]` fixture — returns dict matching `_MOTION_GROUP` params for the default `camera_config`
- [x] Create `tests/test_reconciler.py` — unit tests (AC: 1, 2, 3)
  - [x] `test_reconcile_all_match_returns_no_change` — all GET responses match config → `CameraStatus.NO_CHANGE`, `settings_changed == []`, `set_params` never called (AC: 3)
  - [x] `test_reconcile_smb_ip_mismatch_sets_only_smb_ip` — SMB host differs, rest match → `"smb_ip"` in `settings_changed`, `set_params` called exactly once with SMB host param, no motion SET (AC: 1 inverse + general patch logic)
  - [x] `test_reconcile_motion_sensitivity_mismatch` — motion sensitivity differs → `"motion"` in `settings_changed`, `set_params` called for motion sensitivity only (AC: 2)
  - [x] `test_reconcile_smb_ip_already_matches_no_set` — SMB IP matches config → `"smb_ip"` NOT in `settings_changed`, no SET for that param (AC: 1)
  - [x] `test_reconcile_vapix_error_propagates` — `get_params` raises `VapixError` → `VapixError` propagates out of `reconcile()` uncaught
  - [x] `test_reconcile_returns_camera_result_with_ip_and_model` — result has correct `ip` and `model` from `DiscoveredCamera`
  - [x] Mock `vapix.get_params` and `vapix.set_params` at `cctv.reconciler.vapix` — see patch target note
- [x] Run `pytest` — all tests pass, no regressions

## Dev Notes

### Files to Create / Modify

- `src/cctv/reconciler.py` — **CREATE** (new file)
- `tests/test_reconciler.py` — **CREATE** (new file)
- `tests/conftest.py` — **MODIFY** (add two fixtures)
- `src/cctv/cli.py` — **DO NOT TOUCH** — `apply` stub still raises `NotImplementedError`; executor wiring is Story 3.4
- `src/cctv/executor.py` — **DO NOT CREATE YET** — Story 3.4

### CameraResult and CameraStatus — Define in reconciler.py

These dataclasses are defined in `reconciler.py` in Story 3.1. Downstream modules (`executor.py`, `reporter.py`) will import them from here in Stories 3.4 and 3.5.

```python
# src/cctv/reconciler.py
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional

from requests.auth import HTTPDigestAuth

from cctv.config import CameraConfig
from cctv.scanner import DiscoveredCamera
from cctv import vapix


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
```

### VAPIX Parameter Name Constants — UNVERIFIED

**⚠️ CRITICAL:** These parameter names are best-guess estimates based on VAPIX 3 documentation patterns. They MUST be verified against real Axis hardware (firmware 5.51.7.4) before the tool is used in production. Stories 3.2 and 3.3 own hardware verification and will update these constants.

Declare as module-level constants with `# UNVERIFIED` comments:

```python
# VAPIX parameter groups
_SMB_GROUP = "root.Network.Share"       # UNVERIFIED — verify on firmware 5.51.7.4
_MOTION_GROUP = "root.Motion"           # UNVERIFIED — verify on firmware 5.51.7.4

# SMB parameter names (within root.Network.Share group)
_SMB_HOST = "root.Network.Share.Host"       # SMB share IP — UNVERIFIED
_SMB_SHARE = "root.Network.Share.Share"     # SMB share path — UNVERIFIED
_SMB_USER = "root.Network.Share.Username"   # SMB username — UNVERIFIED
_SMB_PASS = "root.Network.Share.Password"   # SMB password — UNVERIFIED

# Motion parameter names (within root.Motion group)
_MOTION_ENABLED = "root.Motion.M0.Enabled"        # "yes"/"no" — UNVERIFIED
_MOTION_SENSITIVITY = "root.Motion.M0.Sensitivity" # integer string — UNVERIFIED
```

**Boolean encoding:** VAPIX 3 typically encodes booleans as `"yes"`/`"no"`. Use a helper or inline conversion: `"yes" if config.motion_enabled else "no"`. This also needs hardware verification.

**Integer encoding:** `motion_sensitivity` is `int` in `CameraConfig`. Compare against `str(config.motion_sensitivity)` since VAPIX params are always strings.

### reconcile() Implementation Pattern

```python
def reconcile(
    camera: DiscoveredCamera,
    config: CameraConfig,
    auth: HTTPDigestAuth,
) -> CameraResult:
    """Read current camera state, apply only differing settings. Raises VapixError on network failure."""
    changed: list[str] = []

    # --- SMB settings ---
    smb = vapix.get_params(camera.ip, _SMB_GROUP, auth, config.timeout)
    if smb.get(_SMB_HOST) != config.smb_ip:
        vapix.set_params(camera.ip, {_SMB_HOST: config.smb_ip}, auth, config.timeout)
        changed.append("smb_ip")
    if smb.get(_SMB_SHARE) != config.smb_share or \
       smb.get(_SMB_USER) != config.smb_username or \
       smb.get(_SMB_PASS) != config.smb_password:
        vapix.set_params(camera.ip, {
            _SMB_SHARE: config.smb_share,
            _SMB_USER: config.smb_username,
            _SMB_PASS: config.smb_password,
        }, auth, config.timeout)
        changed.append("smb_creds")

    # --- Motion settings ---
    motion = vapix.get_params(camera.ip, _MOTION_GROUP, auth, config.timeout)
    motion_enabled_str = "yes" if config.motion_enabled else "no"
    motion_sensitivity_str = str(config.motion_sensitivity)
    if motion.get(_MOTION_ENABLED) != motion_enabled_str or \
       motion.get(_MOTION_SENSITIVITY) != motion_sensitivity_str:
        vapix.set_params(camera.ip, {
            _MOTION_ENABLED: motion_enabled_str,
            _MOTION_SENSITIVITY: motion_sensitivity_str,
        }, auth, config.timeout)
        changed.append("motion")

    status = CameraStatus.APPLIED if changed else CameraStatus.NO_CHANGE
    return CameraResult(
        ip=camera.ip,
        model=camera.model,
        status=status,
        settings_changed=changed,
    )
```

**Important grouping decisions:**
- `smb_ip` and `smb_creds` are separate labels — consistent with PRD output: `applied (smb_ip, smb_creds, motion)`
- SMB share path + username + password are grouped as `"smb_creds"` (one SET call, one label)
- Motion enabled + sensitivity are grouped as `"motion"` (one SET call, one label)
- This avoids partial-apply edge cases (e.g., updating username but not password)

### Patch Target for Tests

`reconciler.py` imports vapix as a module: `from cctv import vapix`. Patch at:
- `cctv.reconciler.vapix.get_params`
- `cctv.reconciler.vapix.set_params`

```python
from unittest.mock import patch, call
from cctv.reconciler import reconcile, CameraResult, CameraStatus
from cctv.scanner import DiscoveredCamera

def test_reconcile_all_match_returns_no_change(camera_config, mock_auth, smb_params_response, motion_params_response):
    cam = DiscoveredCamera(ip="192.168.1.101", model="AXIS P3245-V")
    with patch("cctv.reconciler.vapix.get_params") as mock_get, \
         patch("cctv.reconciler.vapix.set_params") as mock_set:
        mock_get.side_effect = [smb_params_response, motion_params_response]
        result = reconcile(cam, camera_config, mock_auth)
    assert result.status == CameraStatus.NO_CHANGE
    assert result.settings_changed == []
    mock_set.assert_not_called()
```

### conftest.py Fixtures to Add

The new fixtures return dicts that exactly match the default `camera_config` fixture values, so `reconcile()` produces `NO_CHANGE` when both are used together.

```python
@pytest.fixture
def smb_params_response() -> dict[str, str]:
    """VAPIX SMB params matching the default camera_config fixture — all fields at desired state."""
    from cctv.reconciler import _SMB_HOST, _SMB_SHARE, _SMB_USER, _SMB_PASS
    return {
        _SMB_HOST: "192.168.1.10",   # matches camera_config.smb_ip
        _SMB_SHARE: "/mnt/cctv",     # matches camera_config.smb_share
        _SMB_USER: "smbuser",        # matches camera_config.smb_username
        _SMB_PASS: "smbpass",        # matches camera_config.smb_password
    }

@pytest.fixture
def motion_params_response() -> dict[str, str]:
    """VAPIX motion params matching the default camera_config fixture — all fields at desired state."""
    from cctv.reconciler import _MOTION_ENABLED, _MOTION_SENSITIVITY
    return {
        _MOTION_ENABLED: "yes",  # matches camera_config.motion_enabled = True
        _MOTION_SENSITIVITY: "50",  # matches camera_config.motion_sensitivity = 50
    }
```

### Architecture Constraints — CRITICAL

- **`import requests` FORBIDDEN** — all network calls go through `vapix.py`; reconciler uses `from cctv import vapix`
- **`print()` FORBIDDEN** — `reporter.py` owns all output
- **`config.timeout` always** — never hardcode a timeout value anywhere
- **VapixError MUST propagate** — do not `try/except VapixError` in `reconcile()`; executor.py (Story 3.4) is the failure-isolation boundary
- **`src/cctv/__init__.py` remains EMPTY** — no re-exports
- **`cli.py` DO NOT TOUCH** — `apply` still stubs `NotImplementedError`; wiring happens in Story 3.4
- **`executor.py` DO NOT CREATE** — that is Story 3.4's deliverable

### Module Call Graph (after this story)

```
reconciler.py
  └── vapix.py    (GET current state, SET desired state)
  └── config.py   (CameraConfig — desired state)
  └── scanner.py  (DiscoveredCamera — ip + model)
```

`cli.py` does NOT yet call `reconciler.py`. The `apply` command is still a stub.

### `settings_changed` Labels — Consistency Contract

These labels will be used by `reporter.py` (Story 3.5) to format output lines:
```
192.168.1.101  AXIS P3245-V  applied (smb_ip, smb_creds, motion)
```

Use exactly these string values:
- `"smb_ip"` — SMB host IP changed
- `"smb_creds"` — SMB share path, username, or password changed (grouped)
- `"motion"` — motion enabled state or sensitivity changed (grouped)

Story 3.5 will depend on these exact labels. Do not use different names.

### Previous Story Learnings (from Stories 1.1–2.2)

- **`from __future__ import annotations`** at top of every new module
- **`from cctv import vapix`** module import (not `from cctv.vapix import get_params`) — consistent with scanner.py pattern; required for correct mock patch targets
- **`field(default_factory=list)`** for mutable dataclass defaults — never `= []`
- **`field(repr=False)`** for password fields in dataclasses — already used in `CameraConfig`
- **venv path on Windows:** `.venv/Scripts/python -m pytest` for all test runs
- **`src/cctv/__init__.py` remains EMPTY** — no re-exports, no package-level imports
- **Patch target is the import site:** patch `cctv.reconciler.vapix.get_params`, not `cctv.vapix.get_params`
- **`typer.Exit(code=N)`** not `sys.exit(N)` — but reconciler.py has no exit logic at all; exits are in `cli.py`

### References

- [epics.md#Story 3.1] — acceptance criteria, FR13, FR14, FR16
- [architecture.md#Error Handling & Result Model] — `CameraResult` and `CameraStatus` definitions
- [architecture.md#Process Patterns] — read-before-write pattern implementation
- [architecture.md#Module Responsibility Boundaries] — reconciler.py owns comparison, not output or network
- [2-2-discovery-output-and-subnet-override.md] — reporter.py and cli.py patterns to avoid breaking

## Dev Agent Record

### Agent Model Used

claude-sonnet-4-6

### Debug Log References

- No issues encountered. All tasks completed on first attempt.

### Completion Notes List

- `src/cctv/reconciler.py`: created with `CameraStatus` enum, `CameraResult` dataclass, 8 VAPIX param constants (all marked `# UNVERIFIED`), and `reconcile()` function — reads SMB and motion params via `vapix.get_params`, applies only differing values via `vapix.set_params`, returns `CameraResult(NO_CHANGE)` when all params match; `VapixError` propagates uncaught; no `print()`, no `import requests`, always uses `config.timeout`
- `tests/conftest.py`: added `smb_params_response` and `motion_params_response` fixtures — both keyed to reconciler constants, both pre-matched to default `camera_config` values so combined use yields `NO_CHANGE`
- `tests/test_reconciler.py`: 6 tests covering all 3 ACs — `NO_CHANGE` on full match, `smb_ip` set when host differs, `motion` set when sensitivity differs, `smb_ip` absent when host matches, `VapixError` propagation, `ip`/`model` on result
- 51 pytest tests pass (6 reconciler + 9 CLI + 10 config + 4 reporter + 7 scanner + 15 vapix), 0 failures, 0 regressions

### File List

- src/cctv/reconciler.py
- tests/test_reconciler.py
- tests/conftest.py

### Review Findings

- [x] [Review][Patch] Fixture dict mutated in-place in test [tests/test_reconciler.py:41] — `smb_params_response[_SMB_HOST] = "10.0.0.99"` modifies the fixture dict directly; use `{**smb_params_response, _SMB_HOST: "10.0.0.99"}` copy pattern instead
- [x] [Review][Patch] No test for `motion_enabled=False` path [tests/test_reconciler.py] — `motion_enabled_str = "no"` branch never exercised; add test with `motion_enabled=False` camera config
- [x] [Review][Defer] Empty/absent VAPIX params silently trigger SET calls [src/cctv/reconciler.py:60] — `dict.get()` returns None when param absent → None != expected → spurious write; pre-existing UNVERIFIED param risk, deferred
- [x] [Review][Defer] Partial-apply risk: `set_params` VapixError mid-reconcile leaves camera inconsistent [src/cctv/reconciler.py:61] — by design; executor.py (Story 3.4) is the failure-isolation boundary, deferred
