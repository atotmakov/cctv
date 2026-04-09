# Story 3.2: SMB Share Configuration via VAPIX

Status: done

## Story

As a home sysadmin,
I want the tool to configure the SMB share IP, path, and credentials on each camera,
So that cameras can store recordings to my NAS automatically.

## Acceptance Criteria

1. **Given** a camera with an outdated SMB IP, **when** `cctv apply` runs, **then** the SMB IP is updated via VAPIX to match the config value **and** the change is reflected in `CameraResult.settings_changed` as `"smb_ip"`.

2. **Given** SMB share path or credentials differ from config, **when** `cctv apply` runs, **then** the SMB share path and/or credentials are updated via VAPIX **and** SMB credentials (smb_password value) never appear in stdout, stderr, or error messages.

## Tasks / Subtasks

- [x] Add SMB creds mismatch tests to `tests/test_reconciler.py` (AC: 1, 2)
  - [x] `test_reconcile_smb_share_mismatch_sets_smb_creds` — smb_share differs, smb_ip and creds match → `"smb_creds"` in `settings_changed`, `"smb_ip"` not in `settings_changed`, `set_params` called once with `{_SMB_SHARE, _SMB_USER, _SMB_PASS}` payload (AC: 2)
  - [x] `test_reconcile_smb_username_mismatch_sets_smb_creds` — smb_username differs, rest matches → `"smb_creds"` in `settings_changed`, no smb_ip SET (AC: 2)
  - [x] `test_reconcile_smb_both_ip_and_creds_change` — smb_ip AND smb_share both differ → both `"smb_ip"` and `"smb_creds"` in `settings_changed`, `set_params` called exactly twice with correct payloads (AC: 1, 2)
  - [x] `test_reconcile_smb_ip_matches_creds_differ` — smb_ip matches but smb_password differs → only `"smb_creds"` in `settings_changed`, no SET call targeting `_SMB_HOST` (AC: 1)
  - [x] `test_reconcile_smb_password_not_in_vapix_error` — when `set_params` raises `VapixError("SET params failed: 401 Unauthorized")`, verify that `camera_config.smb_password` value is NOT present in the raised exception message (AC: 2 / NFR7)
- [x] Update VAPIX SMB parameter constant comments in `src/cctv/reconciler.py`
  - [x] If hardware verification was performed: replace `# UNVERIFIED` with `# VERIFIED on firmware 5.51.7.4` on each SMB constant
  - [x] If hardware not yet available: add a TODO comment block above the SMB constants referencing this story, noting verification is still pending
- [x] Run `pytest` — all tests pass, no regressions

## Dev Notes

### What Story 3.1 Already Delivered — DO NOT Reimplement

Story 3.1 built and tested the core reconciler logic. **The following already exists and is correct:**

- `src/cctv/reconciler.py` — full SMB comparison + SET logic:
  - `smb_ip` check: if `smb.get(_SMB_HOST) != config.smb_ip` → SET `{_SMB_HOST: config.smb_ip}`, append `"smb_ip"`
  - `smb_creds` check: if any of `_SMB_SHARE` / `_SMB_USER` / `_SMB_PASS` differ → SET all three together, append `"smb_creds"`
  - Grouping is intentional — avoids partial-apply edge cases (password without username, etc.)
- `tests/test_reconciler.py` — 7 tests already passing covering:
  - `test_reconcile_smb_ip_mismatch_sets_only_smb_ip` — smb_ip SET
  - `test_reconcile_smb_ip_already_matches_no_set` — smb_ip no-op
  - `test_reconcile_all_match_returns_no_change` — full NO_CHANGE

**Do NOT touch `cli.py`** — `apply` still stubs `NotImplementedError`; wiring is Story 3.4.

### New Tests Required — Exact Pattern

All new tests follow the existing pattern. Import what's needed from `cctv.reconciler` and patch at `cctv.reconciler.vapix.*`.

```python
from __future__ import annotations
from unittest.mock import patch, call
from cctv.reconciler import (
    reconcile, CameraResult, CameraStatus,
    _SMB_HOST, _SMB_SHARE, _SMB_USER, _SMB_PASS,
    _MOTION_ENABLED, _MOTION_SENSITIVITY,
)
from cctv.scanner import DiscoveredCamera
from cctv.vapix import VapixError

CAM = DiscoveredCamera(ip="192.168.1.101", model="AXIS P3245-V")
```

**Pattern for smb_creds mismatch (share differs):**
```python
def test_reconcile_smb_share_mismatch_sets_smb_creds(
    camera_config, mock_auth, smb_params_response, motion_params_response
) -> None:
    smb_params_response = {**smb_params_response, _SMB_SHARE: "/old/path"}  # differs
    with patch("cctv.reconciler.vapix.get_params") as mock_get, \
         patch("cctv.reconciler.vapix.set_params") as mock_set:
        mock_get.side_effect = [smb_params_response, motion_params_response]
        result = reconcile(CAM, camera_config, mock_auth)
    assert result.status == CameraStatus.APPLIED
    assert "smb_creds" in result.settings_changed
    assert "smb_ip" not in result.settings_changed
    mock_set.assert_called_once_with(
        CAM.ip,
        {_SMB_SHARE: camera_config.smb_share,
         _SMB_USER: camera_config.smb_username,
         _SMB_PASS: camera_config.smb_password},
        mock_auth,
        camera_config.timeout,
    )
```

**Pattern for combined smb_ip + smb_creds change (two SET calls):**
```python
def test_reconcile_smb_both_ip_and_creds_change(
    camera_config, mock_auth, smb_params_response, motion_params_response
) -> None:
    smb_params_response = {
        **smb_params_response,
        _SMB_HOST: "10.0.0.99",      # differs
        _SMB_SHARE: "/old/path",     # differs
    }
    with patch("cctv.reconciler.vapix.get_params") as mock_get, \
         patch("cctv.reconciler.vapix.set_params") as mock_set:
        mock_get.side_effect = [smb_params_response, motion_params_response]
        result = reconcile(CAM, camera_config, mock_auth)
    assert result.status == CameraStatus.APPLIED
    assert "smb_ip" in result.settings_changed
    assert "smb_creds" in result.settings_changed
    assert mock_set.call_count == 2
    mock_set.assert_any_call(
        CAM.ip, {_SMB_HOST: camera_config.smb_ip}, mock_auth, camera_config.timeout
    )
    mock_set.assert_any_call(
        CAM.ip,
        {_SMB_SHARE: camera_config.smb_share,
         _SMB_USER: camera_config.smb_username,
         _SMB_PASS: camera_config.smb_password},
        mock_auth, camera_config.timeout,
    )
```

**Pattern for credential safety test:**
```python
def test_reconcile_smb_password_not_in_vapix_error(
    camera_config, mock_auth, smb_params_response, motion_params_response
) -> None:
    """NFR7: smb_password value must not appear in any VapixError message."""
    smb_params_response = {**smb_params_response, _SMB_PASS: "wrongpass"}  # triggers creds SET
    error_msg = "SET params on 192.168.1.101 failed: 401 Unauthorized"
    with patch("cctv.reconciler.vapix.get_params") as mock_get, \
         patch("cctv.reconciler.vapix.set_params", side_effect=VapixError(error_msg)):
        mock_get.side_effect = [smb_params_response, motion_params_response]
        import pytest
        with pytest.raises(VapixError) as exc_info:
            reconcile(CAM, camera_config, mock_auth)
    assert camera_config.smb_password not in str(exc_info.value)
```

### VAPIX SMB Parameter Constants — UNVERIFIED

The constants in `reconciler.py` are currently:
```python
_SMB_GROUP = "root.Network.Share"        # UNVERIFIED — verify on firmware 5.51.7.4
_SMB_HOST = "root.Network.Share.Host"        # SMB share IP — UNVERIFIED
_SMB_SHARE = "root.Network.Share.Share"      # SMB share path — UNVERIFIED
_SMB_USER = "root.Network.Share.Username"    # SMB username — UNVERIFIED
_SMB_PASS = "root.Network.Share.Password"    # SMB password — UNVERIFIED
```

**Hardware verification task:** Query a real Axis P3245-V (firmware 5.51.7.4) with:
```
GET http://<ip>/axis-cgi/param.cgi?action=list&group=root.Network
```
and examine the response to confirm actual param key names. Update constants if they differ. Mark `# VERIFIED on firmware 5.51.7.4` once confirmed.

If hardware is not yet available: leave constants as UNVERIFIED, add inline TODO comment noting Story 3.2 owns this verification.

### Architecture Constraints — CRITICAL (same as Story 3.1)

- **`import requests` FORBIDDEN** in reconciler.py — all network via `from cctv import vapix`
- **`print()` FORBIDDEN** — reporter.py owns all output
- **`config.timeout` always** — never hardcode
- **VapixError MUST propagate** from `reconcile()` — executor.py (Story 3.4) catches it
- **`src/cctv/__init__.py` remains EMPTY**
- **`cli.py` DO NOT TOUCH**
- **`executor.py` DO NOT CREATE** — Story 3.4
- **`reporter.py` DO NOT TOUCH** — Story 3.5

### Fixture dict mutation — NEVER mutate, always copy

```python
# CORRECT — dict copy pattern (enforced since Story 3.1 review)
smb_params_response = {**smb_params_response, _SMB_HOST: "10.0.0.99"}

# WRONG — mutates fixture, fragile
smb_params_response[_SMB_HOST] = "10.0.0.99"
```

### settings_changed Labels — Consistency Contract (do not change)

```
"smb_ip"    — SMB host IP changed
"smb_creds" — SMB share path, username, or password changed (grouped SET)
"motion"    — motion enabled state or sensitivity changed (grouped SET)
```

These exact labels will be consumed by `reporter.py` in Story 3.5.

### Patch Targets

```python
patch("cctv.reconciler.vapix.get_params")   # GET calls
patch("cctv.reconciler.vapix.set_params")   # SET calls
```

### Module Call Graph (after this story — unchanged from 3.1)

```
reconciler.py
  └── vapix.py    (GET current state, SET desired state)
  └── config.py   (CameraConfig — desired state)
  └── scanner.py  (DiscoveredCamera — ip + model)
```

### Previous Story Learnings (Stories 1.1–3.1)

- `from __future__ import annotations` at top of every new module
- `from cctv import vapix` module import — required for correct mock patch targets
- `field(default_factory=list)` for mutable dataclass defaults
- **venv path on Windows:** `.venv/Scripts/python -m pytest`
- Patch target is the import site: `cctv.reconciler.vapix.*`, NOT `cctv.vapix.*`
- `{**fixture_dict, key: new_value}` copy pattern — never mutate fixture dicts in-place

### Files to Create / Modify

- `tests/test_reconciler.py` — **MODIFY** (add 5 new tests)
- `src/cctv/reconciler.py` — **MODIFY** (update UNVERIFIED comments only — no logic changes)
- `src/cctv/cli.py` — **DO NOT TOUCH**
- `src/cctv/executor.py` — **DO NOT CREATE**

### References

- [epics.md#Story 3.2] — acceptance criteria, FR17, FR18
- [architecture.md#Error Handling & Result Model] — NFR7 credential hygiene
- [architecture.md#Process Patterns] — read-before-write pattern
- [3-1-read-before-write-state-reconciliation.md] — existing reconciler.py implementation

## Dev Agent Record

### Agent Model Used

claude-sonnet-4-6

### Debug Log References

- No issues encountered. All tasks completed on first attempt.

### Completion Notes List

- `tests/test_reconciler.py`: added 5 new tests — `test_reconcile_smb_share_mismatch_sets_smb_creds`, `test_reconcile_smb_username_mismatch_sets_smb_creds`, `test_reconcile_smb_both_ip_and_creds_change`, `test_reconcile_smb_ip_matches_creds_differ`, `test_reconcile_smb_password_not_in_vapix_error` — covering smb_creds branch (all three creds fields), combined smb_ip+smb_creds two-SET scenario, and NFR7 credential safety; all use copy pattern (`{**fixture, key: val}`) and patch at `cctv.reconciler.vapix.*`
- `src/cctv/reconciler.py`: added TODO comment block above SMB constants documenting hardware verification query for firmware 5.51.7.4; constants remain UNVERIFIED pending physical hardware access
- 57 pytest tests pass (12 reconciler + 9 CLI + 10 config + 4 reporter + 7 scanner + 15 vapix), 0 failures, 0 regressions

### File List

- tests/test_reconciler.py
- src/cctv/reconciler.py

### Review Findings

- [x] [Review][Patch] Vacuous `for c in mock_set.call_args_list` assertion in two tests [tests/test_reconciler.py] — `test_reconcile_smb_username_mismatch_sets_smb_creds` and `test_reconcile_smb_ip_matches_creds_differ` iterate call_args_list to check `_SMB_HOST not in c.args[1]`; if set_params is never called, the loop body never executes and the assertion passes vacuously — add `assert mock_set.call_count >= 1` before the loop in each test
- [x] [Review][Patch] Missing `"motion" not in result.settings_changed` assertion in smb_share mismatch test [tests/test_reconciler.py] — `test_reconcile_smb_share_mismatch_sets_smb_creds` uses `assert_called_once_with` which implicitly catches a second SET call (call_count>1 fails), but doesn't explicitly assert motion did not fire; add `assert "motion" not in result.settings_changed`
- [x] [Review][Patch] `motion_params_response[_MOTION_SENSITIVITY] = "99"` mutates fixture dict in-place [tests/test_reconciler.py:64] — missed in Story 3.1 code review; use copy pattern: `motion_params_response = {**motion_params_response, _MOTION_SENSITIVITY: "99"}`
- [x] [Review][Defer] NFR7 test trivially passes — hand-crafted error message never contains password [tests/test_reconciler.py] — structural protection exists: vapix.set_params never echoes params into error message; a stronger test would use a `raising_set` side_effect that embeds its args in the message; defer to hardening pass, deferred
- [x] [Review][Defer] SET call order (smb_ip before smb_creds) not pinned in combined test [tests/test_reconciler.py] — `assert_any_call` does not enforce ordering; on real hardware order may be semantically significant; deferred pre-existing design
- [x] [Review][Defer] VapixError from set_params path untested (smb_ip or smb_creds SET raises) [tests/test_reconciler.py] — pre-existing from Story 3.1; test_reconcile_vapix_error_propagates only covers get_params raising, deferred
- [x] [Review][Defer] Empty dict from get_params (unconfigured/factory-reset camera) — no test [src/cctv/reconciler.py] — pre-existing gap; UNVERIFIED param names make this a hardware-verification prerequisite, deferred
- [x] [Review][Defer] VapixError from second (motion) get_params call untested [tests/test_reconciler.py] — pre-existing from Story 3.1, deferred
- [x] [Review][Defer] motion_sensitivity boundary values (0, 100) and float slip-through untested [src/cctv/reconciler.py:88] — pre-existing; `str(config.motion_sensitivity)` with float value produces "50.0" not "50" causing permanent diff loop on real hardware; defer to config hardening pass, deferred
