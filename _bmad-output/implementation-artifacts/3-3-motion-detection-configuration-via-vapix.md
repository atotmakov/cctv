# Story 3.3: Motion Detection Configuration via VAPIX

Status: done

## Story

As a home sysadmin,
I want the tool to configure motion detection enabled state and sensitivity on each camera,
So that all cameras have consistent motion detection behaviour without manual UI interaction.

## Acceptance Criteria

1. **Given** motion detection is disabled on a camera but `motion_detection.enabled: true` in config, **when** `cctv apply` runs, **then** motion detection is enabled on that camera via VAPIX **and** `"motion"` is included in `CameraResult.settings_changed`.

2. **Given** motion sensitivity differs from config value, **when** `cctv apply` runs, **then** motion sensitivity is updated to match the config value via VAPIX.

3. **Given** both motion enabled and sensitivity already match the config, **when** `cctv apply` runs for that camera, **then** no motion detection SET calls are made.

## Tasks / Subtasks

- [x] Add motion detection tests to `tests/test_reconciler.py` (AC: 1, 2, 3)
  - [x] `test_reconcile_motion_enabled_mismatch_enables_motion` — camera has `"no"` for enabled, config `motion_enabled=True` → `"motion"` in `settings_changed`, `set_params` called once with `{_MOTION_ENABLED: "yes", _MOTION_SENSITIVITY: "50"}` (AC: 1)
  - [x] `test_reconcile_motion_both_fields_differ` — both `_MOTION_ENABLED` and `_MOTION_SENSITIVITY` differ from config → `"motion"` appears exactly once in `settings_changed`, single grouped `set_params` call with both fields (AC: 1, 2)
  - [x] `test_reconcile_motion_already_matches_no_motion_set` — motion group exactly matches config (enabled="yes", sensitivity="50"), SMB also matches → `"motion"` NOT in `settings_changed`, no SET targeting `_MOTION_ENABLED` or `_MOTION_SENSITIVITY` (AC: 3)
- [x] Update VAPIX motion parameter constant comments in `src/cctv/reconciler.py`
  - [x] If hardware verification was performed: replace `# UNVERIFIED` with `# VERIFIED on firmware 5.51.7.4` on each motion constant
  - [x] If hardware not yet available: add a TODO comment block above the motion constants referencing this story, noting verification is still pending
- [x] Run `pytest` — all tests pass, no regressions

## Dev Notes

### What Already Exists — DO NOT Reimplement

Story 3.1 built the complete motion reconciler logic. **The following already exists and is correct:**

- `src/cctv/reconciler.py` — motion comparison + SET:
  - GET `_MOTION_GROUP` via `vapix.get_params`
  - Compute `motion_enabled_str = "yes" if config.motion_enabled else "no"`
  - Compute `motion_sensitivity_str = str(config.motion_sensitivity)`
  - If either `_MOTION_ENABLED` or `_MOTION_SENSITIVITY` differ → single grouped `set_params` call with both fields, append `"motion"` once
- `tests/test_reconciler.py` — existing motion tests (12 tests total, do not break):
  - `test_reconcile_motion_sensitivity_mismatch` — sensitivity differs → motion SET (AC2 covered)
  - `test_reconcile_motion_disabled_sets_no` — config=False, camera="yes" → SET with "no"
  - `test_reconcile_motion_disabled_sets_no` uses `camera_config.motion_enabled = False` (dataclass mutation, safe per-test)
  - `test_reconcile_all_match_returns_no_change` — full NO_CHANGE (AC3 indirectly covered)

**Do NOT touch `cli.py`** — `apply` still stubs `NotImplementedError`; Story 3.4 wires it.

### New Tests Required — Exact Patterns

**AC1 — camera disabled, config wants enabled:**
```python
def test_reconcile_motion_enabled_mismatch_enables_motion(
    camera_config, mock_auth, smb_params_response, motion_params_response
) -> None:
    """AC1: camera has 'no' but config.motion_enabled=True → SET to 'yes'."""
    motion_params_response = {**motion_params_response, _MOTION_ENABLED: "no"}  # camera disabled

    with patch("cctv.reconciler.vapix.get_params") as mock_get, \
         patch("cctv.reconciler.vapix.set_params") as mock_set:
        mock_get.side_effect = [smb_params_response, motion_params_response]
        result = reconcile(CAM, camera_config, mock_auth)

    assert result.status == CameraStatus.APPLIED
    assert "motion" in result.settings_changed
    assert result.settings_changed.count("motion") == 1  # "motion" appears exactly once
    mock_set.assert_called_once_with(
        CAM.ip,
        {_MOTION_ENABLED: "yes", _MOTION_SENSITIVITY: "50"},
        mock_auth,
        camera_config.timeout,
    )
```

**Both fields differ — single grouped SET:**
```python
def test_reconcile_motion_both_fields_differ(
    camera_config, mock_auth, smb_params_response, motion_params_response
) -> None:
    """Both motion_enabled and motion_sensitivity differ → one grouped SET, 'motion' once."""
    motion_params_response = {
        **motion_params_response,
        _MOTION_ENABLED: "no",    # differs (config=True → "yes")
        _MOTION_SENSITIVITY: "99",  # differs (config=50)
    }

    with patch("cctv.reconciler.vapix.get_params") as mock_get, \
         patch("cctv.reconciler.vapix.set_params") as mock_set:
        mock_get.side_effect = [smb_params_response, motion_params_response]
        result = reconcile(CAM, camera_config, mock_auth)

    assert result.status == CameraStatus.APPLIED
    assert "motion" in result.settings_changed
    assert result.settings_changed.count("motion") == 1
    mock_set.assert_called_once_with(
        CAM.ip,
        {_MOTION_ENABLED: "yes", _MOTION_SENSITIVITY: "50"},
        mock_auth,
        camera_config.timeout,
    )
```

**AC3 — motion already matches:**
```python
def test_reconcile_motion_already_matches_no_motion_set(
    camera_config, mock_auth, smb_params_response, motion_params_response
) -> None:
    """AC3: motion group matches config → no motion SET, 'motion' not in settings_changed."""
    # Both fixtures already match config — no changes needed
    with patch("cctv.reconciler.vapix.get_params") as mock_get, \
         patch("cctv.reconciler.vapix.set_params") as mock_set:
        mock_get.side_effect = [smb_params_response, motion_params_response]
        result = reconcile(CAM, camera_config, mock_auth)

    assert "motion" not in result.settings_changed
    # Verify no SET call targets any motion param
    for c in mock_set.call_args_list:
        assert _MOTION_ENABLED not in c.args[1]
        assert _MOTION_SENSITIVITY not in c.args[1]
```

### VAPIX Motion Parameter Constants — UNVERIFIED

The constants in `reconciler.py` are currently:
```python
_MOTION_GROUP = "root.Motion"            # UNVERIFIED — verify on firmware 5.51.7.4
_MOTION_ENABLED = "root.Motion.M0.Enabled"         # "yes"/"no" — UNVERIFIED
_MOTION_SENSITIVITY = "root.Motion.M0.Sensitivity"  # integer string — UNVERIFIED
```

**Hardware verification task:** Query a real Axis P3245-V (firmware 5.51.7.4) with:
```
GET http://<ip>/axis-cgi/param.cgi?action=list&group=root.Motion
```
Examine the response to confirm actual param key names. Note whether `M0` is the correct motion detection window index. Update constants if they differ. Mark `# VERIFIED on firmware 5.51.7.4` once confirmed.

If hardware is not yet available: add a TODO comment block above the motion constants noting this story owns verification.

### Key Implementation Detail — Grouped SET

Motion enabled + sensitivity are always SET together in one call:
```python
# reconciler.py (existing — do not change)
if (
    motion.get(_MOTION_ENABLED) != motion_enabled_str
    or motion.get(_MOTION_SENSITIVITY) != motion_sensitivity_str
):
    vapix.set_params(camera.ip, {
        _MOTION_ENABLED: motion_enabled_str,
        _MOTION_SENSITIVITY: motion_sensitivity_str,
    }, auth, config.timeout)
    changed.append("motion")
```
This means: either field differing triggers writing BOTH fields. Tests must assert a single grouped call, not two separate calls.

### Architecture Constraints — CRITICAL

- **`import requests` FORBIDDEN** — all network via `from cctv import vapix`
- **`print()` FORBIDDEN** — reporter.py owns all output
- **`config.timeout` always** — never hardcode
- **VapixError MUST propagate** from `reconcile()` — executor.py (Story 3.4) catches it
- **`src/cctv/__init__.py` remains EMPTY**
- **`cli.py` DO NOT TOUCH**
- **`executor.py` DO NOT CREATE** — Story 3.4
- **`reporter.py` DO NOT TOUCH** — Story 3.5

### Fixture dict copy pattern — always use copy, never mutate

```python
# CORRECT
motion_params_response = {**motion_params_response, _MOTION_ENABLED: "no"}

# WRONG — mutates fixture
motion_params_response[_MOTION_ENABLED] = "no"
```

### Patch Targets

```python
patch("cctv.reconciler.vapix.get_params")   # always 2 side_effects: [smb_response, motion_response]
patch("cctv.reconciler.vapix.set_params")   # SET calls
```

### Previous Story Learnings (Stories 3.1–3.2)

- `from __future__ import annotations` at top of every new module
- `{**fixture, key: val}` copy pattern — NEVER mutate fixture dicts in-place
- `assert mock_set.call_count >= 1` before any for-loop iterating `call_args_list` (Story 3.2 review)
- `result.settings_changed.count("motion") == 1` to verify label appears exactly once
- Patch at `cctv.reconciler.vapix.*`, NOT `cctv.vapix.*`
- **venv path on Windows:** `.venv/Scripts/python -m pytest`

### Files to Create / Modify

- `tests/test_reconciler.py` — **MODIFY** (add 3 new tests)
- `src/cctv/reconciler.py` — **MODIFY** (update motion constant comments only — no logic changes)
- `src/cctv/cli.py` — **DO NOT TOUCH**
- `src/cctv/executor.py` — **DO NOT CREATE**

### References

- [epics.md#Story 3.3] — acceptance criteria, FR19, FR20
- [architecture.md#Process Patterns] — read-before-write pattern
- [3-1-read-before-write-state-reconciliation.md] — existing reconciler.py implementation
- [3-2-smb-share-configuration-via-vapix.md] — patterns from SMB story

## Dev Agent Record

### Agent Model Used

claude-sonnet-4-6

### Debug Log References

- No issues encountered. All tasks completed on first attempt.

### Completion Notes List

- `tests/test_reconciler.py`: added 3 new tests — `test_reconcile_motion_enabled_mismatch_enables_motion` (AC1: camera="no", config=True → SET "yes"), `test_reconcile_motion_both_fields_differ` (AC1+2: both fields differ → single grouped SET), `test_reconcile_motion_already_matches_no_motion_set` (AC3: motion matches → no SET, loop verifies no motion params in any SET call); all use copy pattern for fixture dicts
- `src/cctv/reconciler.py`: added TODO comment block above motion constants documenting hardware verification query for firmware 5.51.7.4; confirms M0 window index needs verification; constants remain UNVERIFIED pending physical hardware
- 60 pytest tests pass (15 reconciler + 9 CLI + 10 config + 4 reporter + 7 scanner + 15 vapix), 0 failures, 0 regressions

### File List

- tests/test_reconciler.py
- src/cctv/reconciler.py

### Review Findings

- [x] [Review][Patch] AC3 test uses vacuous for-loop and missing status assertion [tests/test_reconciler.py] — `test_reconcile_motion_already_matches_no_motion_set` iterates `call_args_list` which is empty when `set_params` never called (vacuous); also missing `assert result.status == CameraStatus.NO_CHANGE`; fix: replace for-loop with `mock_set.assert_not_called()` and add status assertion
- [x] [Review][Defer] UNVERIFIED motion param constants used in prod and tests [src/cctv/reconciler.py] — `_MOTION_ENABLED`, `_MOTION_SENSITIVITY` are pre-existing UNVERIFIED; tests pass green while firmware may ignore unknown keys silently; hardware verification pending, deferred
- [x] [Review][Defer] `mock_get.side_effect` ordering is an implicit fragile contract [tests/test_reconciler.py] — assumes exactly 2 `get_params` calls in SMB-first order; pre-existing pattern throughout suite; no `mock_get.call_count` assertion; deferred
- [x] [Review][Defer] `motion.get()` returns None when key absent — silent always-trigger SET [src/cctv/reconciler.py] — if firmware returns wrong group name or missing key, `None != config_str` unconditionally fires SET every run; pre-existing UNVERIFIED param risk, deferred
- [x] [Review][Defer] `motion_enabled=False` + camera already `"no"` + sensitivity differs — untested path [tests/test_reconciler.py] — the `or` branch could fire on sensitivity alone when enabled is already correct; pre-existing gap, deferred
- [x] [Review][Defer] motion_sensitivity boundary values (0, float) untested [src/cctv/reconciler.py] — `str(0)` is `"0"` (fine); `str(50.0)` is `"50.0"` (breaks); pre-existing, already in deferred-work.md, deferred
- [x] [Review][Defer] Non-canonical numeric string from camera (e.g., `"050"` for 50) causes spurious SET [src/cctv/reconciler.py] — strict string equality `"050" != "50"` triggers write every run; hardware verification gap, deferred
