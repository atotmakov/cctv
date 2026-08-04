# Story 4.1: Camera Status Collection and Text Report

Status: done

## Story

As a home sysadmin,
I want `cctv status <config.yaml>` to print each discovered camera's current motion detection, action rules, SMB share, timezone, and retention settings,
so that I can audit my fleet's live state from the terminal without opening any camera's web UI.

## Acceptance Criteria

1. **Given** a valid `cameras.yaml` and reachable cameras on the configured subnet, **when** I run `cctv status cameras.yaml`, **then** every discovered camera is probed read-only — no `set_params`, `add_action_rule`, `add_action_configuration`, `upload_application`, or `start_application` call is ever made — **and** for each camera the output includes: motion app name/nice-name/status, motion enabled state + sensitivity + window presence, all configured action rules with their linked action configuration (name, trigger topic, target template, pre/post duration), SMB share IP/path/username (never password), current timezone, and recording retention in days.
2. **Given** a camera is unreachable or a VAPIX call for one camera fails mid-collection, **when** `cctv status` runs across a multi-camera fleet, **then** that camera's block reports the failure reason and the remaining cameras are still reported — one bad camera does not abort the whole run.
3. **Given** `--subnet <CIDR>` is passed, **when** `cctv status cameras.yaml --subnet <CIDR>` runs, **then** the override subnet is used for discovery instead of the one in the config file (same behaviour as `list`/`apply`).
4. **Given** no cameras are found on the subnet, **when** `cctv status` completes, **then** the output states no cameras were found and the process exits with code 2 (same convention as `cctv list`).

## Tasks / Subtasks

- [ ] Preparatory refactor in `src/cctv/reconciler.py`: promote 5 pure helpers from private to public, no behavior change (AC: 1)
  - [ ] `_parse_motion_windows` → `parse_motion_windows`
  - [ ] `_find_full_frame_window_id` → `find_full_frame_window_id`
  - [ ] `_full_frame_sensitivity_key` → `full_frame_sensitivity_key`
  - [ ] `_find_vmd_app` → `find_vmd_app`
  - [ ] `_VMD_APP_NAMES` → `VMD_APP_NAMES`, `_VMD_NICE_NAME` → `VMD_NICE_NAME`
  - [ ] Update all internal call sites in `reconciler.py`; run `pytest tests/test_reconciler.py` — must stay green with zero test changes (these functions aren't imported by name in any existing test, confirmed by grep)
- [ ] Create `src/cctv/status.py` — new module, read-only, mirrors `reconciler.py`'s role but never calls a write endpoint (AC: 1, 2)
  - [ ] `ActionRuleStatus` dataclass: `name: str`, `topic: str`, `enabled: bool`, `target_template: str`, `pre_duration_ms: Optional[str]`, `post_duration_ms: Optional[str]`
  - [ ] `CameraStatusResult` dataclass: `ip: str`, `model: Optional[str]`, `motion_app_name: Optional[str]`, `motion_app_nice_name: Optional[str]`, `motion_app_status: Optional[str]`, `motion_enabled: bool`, `motion_sensitivity: Optional[str]`, `motion_window_present: bool`, `action_rules: list[ActionRuleStatus]`, `smb_ip: Optional[str]`, `smb_share: Optional[str]`, `smb_username: Optional[str]`, `timezone: Optional[str]`, `retention_days: Optional[str]`, `error: Optional[str] = None`
  - [ ] `collect_status(camera: DiscoveredCamera, config: CameraConfig, auth: HTTPDigestAuth) -> CameraStatusResult` — GET-only: `vapix.get_params` (SMB/Motion/Storage/Time groups), `vapix.get_applications`, `vapix.get_action_configurations`, `vapix.get_action_rules`. Reuses the 5 promoted helpers from `reconciler.py` for motion window/app parsing — do not reimplement that logic.
  - [ ] Join action rules to configs via `primary_action == config_id` (same pattern as `reconciler._ensure_motion_action_rule`'s `cfg_by_id` map) to populate `target_template`/durations
  - [ ] `collect_all(cameras, config, auth) -> list[CameraStatusResult]` — calls `collect_status` per camera in a `try/except VapixError`, catches per-camera and sets `CameraStatusResult(ip=..., model=..., error=str(exc), ...other fields None/empty...)` — mirrors `executor.apply_all`'s failure-isolation pattern (AC: 2)
- [ ] Add `print_camera_status(results: list[CameraStatusResult]) -> int` to `src/cctv/reporter.py` (AC: 1, 2)
  - [ ] Per-camera multi-line block format (see Dev Notes — Output Format)
  - [ ] Failed camera: `<ip>  <model>  STATUS UNAVAILABLE — <error>` single line, no sub-fields
  - [ ] Returns `1` if any camera has `error` set, else `0` — mirrors `print_apply_results`' return-exit-code pattern
- [ ] Add `status` command to `src/cctv/cli.py` (AC: 1, 2, 3, 4)
  - [ ] Signature mirrors `apply`: `config: Path` argument (`exists=True` etc.), `--subnet` option via existing `_validate_subnet` callback
  - [ ] Do NOT add `--json` in this story — Story 4.2 owns it
  - [ ] Flow: `load_config` → `scanner.scan` → `status.collect_all` → `reporter.print_camera_status` → `typer.Exit(code=...)`
  - [ ] No cameras found → same handling as `list_cameras`: exit code 2
- [ ] Tests (AC: all)
  - [ ] `tests/test_status.py` — new file, mirrors `test_reconciler.py`/`test_executor.py` conventions: mock `vapix.get_params`/`get_applications`/`get_action_configurations`/`get_action_rules`, assert zero calls to any write function, assert correct field population, assert per-camera failure isolation
  - [ ] `tests/test_reporter.py` — add tests for `print_camera_status` (full block, failed-camera line, exit code 0/1, stdout-only — no stderr writes)
  - [ ] `tests/test_cli.py` — add `status` command wiring tests (mirrors existing `list`/`apply` CLI tests): subnet override, no-cameras exit 2, config error exit 2
  - [ ] Add fixtures to `tests/conftest.py` following existing naming (`*_params_response` dicts, `InstalledApplication`/`ActionConfiguration`/`ActionRule` instances) — reuse existing fixtures where field values already match (e.g. `motion_params_response`, `vmd_app_running`, `motion_action_config`, `motion_action_rule`)
- [ ] Run full `pytest` — all tests pass, zero regressions in Epics 1–3

## Dev Notes

### What Already Exists — Reuse, Do Not Reimplement

Everything this story needs on the VAPIX side already exists in `vapix.py` (built across Stories 1.4, 3.2, 3.3, 3.6) — **no changes to `vapix.py` are needed for this story**:
- `get_params(ip, group, auth, timeout)` — reuse for SMB (`root.NetworkShare`), Motion (`root.Motion`), Storage (`root.Storage`), Time (`root.Time`) groups
- `get_applications(ip, auth, timeout)` → `list[InstalledApplication]` — motion app status
- `get_action_configurations(ip, auth, timeout)` → `list[ActionConfiguration]`
- `get_action_rules(ip, auth, timeout)` → `list[ActionRule]`

The exact VAPIX group/param name strings you need are already verified and live as constants in `reconciler.py` — **re-declare the same literal values as new constants in `status.py`** (e.g. `_SMB_GROUP = "root.NetworkShare"`, `_MOTION_GROUP = "root.Motion"`, `_STORAGE_GROUP = "root.Storage"`, `_STORAGE_RETENTION = "root.Storage.S1.CleanupMaxAge"`, `_TIME_GROUP = "root.Time"`, `_TIME_TIMEZONE = "root.Time.POSIXTimeZone"`, `_SMB_HOST/_SMB_SHARE/_SMB_USER` — copy exact values from `reconciler.py`). This is a deliberate choice, not an oversight: these are `reconciler.py`-private constants (leading underscore) by design, and `status.py` is a peer module with a different concern (reporting vs. convergence) — duplicating a handful of literal strings is preferable to importing another module's private names or introducing a shared-constants module nobody asked for.

**The one thing that IS worth sharing (not duplicating)** is actual parsing *logic*, not literal strings — see the preparatory refactor task: `parse_motion_windows`, `find_full_frame_window_id`, `full_frame_sensitivity_key`, and `find_vmd_app` are pure, already-tested functions in `reconciler.py`. Promote them to public (drop the leading underscore) and import them into `status.py` rather than re-deriving the same window/app-matching logic a second time.

### Hardware-Verified Edge Cases to Handle (from Stories 3.3 and 3.6 — do not regress these)

- **Empty `root.Motion` response** (VMD4 cameras, e.g. the real AXIS M3085-V on this fleet) — `get_params` returns `{}`. `motion_window_present` must be `False`, `motion_sensitivity` must be `None`; do not crash or treat this as an error.
- **VMD app package `Name` varies** (`"vmd"` on VMD3/VMD4 vs. `"VideoMotionDetection"` on the legacy 2.2.1 `.eap` — confirmed on real AXIS M3005 hardware in Story 3.6) — this is exactly why `find_vmd_app` (name-or-nice-name matching) must be reused rather than hardcoding `"vmd"`.
- **App status `"Idle"` is a normal running state** for the legacy app (Story 3.6 finding) — report it as-is (`motion_app_status = "Idle"`), don't normalize it to "not running."

### Output Format (text — Story 4.2 adds `--json` on top of this, unchanged)

```
192.168.1.101  AXIS M3005 Network Camera
  motion app:   VideoMotionDetection (AXIS Video Motion Detection) — Running
  motion:       enabled, sensitivity 90, full-frame window
  action rules: cctv_motion_record — motion → record to NetworkShare (pre 5000ms, post 2000ms)
  smb share:    192.168.1.100:/cctv  (user: cctv)
  time:         MSK-3
  retention:    33 days

192.168.1.72  AXIS M3085-V Network Camera
  motion app:   vmd (AXIS Video Motion Detection) — Running
  motion:       enabled, sensitivity 95, no window configured
  action rules: none configured
  smb share:    192.168.1.100:/cctv  (user: cctv)
  time:         MSK-3
  retention:    33 days

192.168.1.60  AXIS M3005 Network Camera  STATUS UNAVAILABLE — Connection timeout to 192.168.1.60
```
[Source: prd.md#Output Format, exact block shape from that spec — implementer may adjust label alignment/wording but must keep one block per camera and the field set from AC1]

### Exit Code Convention (not fully spelled out in epics.md AC — this is the design decision, follow it)

`status` mirrors `apply`'s exit-code contract, not `list`'s: `0` if every camera's status was collected successfully, `1` if one or more camera collections failed (mirrors FR25's pattern, applied to `CameraResult.status == FAILED` → here, `CameraStatusResult.error is not None`), `2` only for the fatal/pre-flight cases (config error, no cameras found at all) — same as `list_cameras`/`apply` already do in `cli.py`.

### Architecture Constraints — CRITICAL (unchanged project-wide rules, apply to this story too)

- **`import requests` FORBIDDEN** outside `vapix.py` — `status.py` calls `vapix.*`, never `requests` directly
- **`print()` FORBIDDEN** outside `reporter.py`
- **This story makes ZERO write calls** — no `set_params`, `add_action_rule`, `add_action_configuration`, `remove_action_rule`, `remove_action_configuration`, `upload_application`, `start_application` anywhere in `status.py`. This is the core safety property of the whole command (NFR3/NFR8 spirit) — a test must assert these are never called.
- **`config.timeout` always** — never hardcode
- **Credentials never in output** — SMB/camera passwords must never appear in `CameraStatusResult` fields or printed output (NFR7)
- **`cli.py` DO NOT add `--json`** — Story 4.2 scope only

### Files to Create / Modify

- `src/cctv/reconciler.py` — MODIFY (promote 5 helpers to public, no behavior change)
- `src/cctv/status.py` — CREATE
- `src/cctv/reporter.py` — MODIFY (add `print_camera_status`)
- `src/cctv/cli.py` — MODIFY (add `status` command)
- `tests/test_status.py` — CREATE
- `tests/test_reporter.py`, `tests/test_cli.py`, `tests/conftest.py` — MODIFY

### References

- [epics.md#Story 4.1] — acceptance criteria, FR29–FR33
- [prd.md#Command Structure, #Output Format] — `cctv status` CLI shape and example block
- [architecture.md#Module Responsibility Boundaries] — `requests` only in `vapix.py`, `print()` only in `reporter.py`
- [3-3-motion-detection-configuration-via-vapix.md], [3-6-legacy-camera-vmd-app-detection-and-install.md] — source of the motion/app parsing logic being reused, and the hardware-verified edge cases above
- [3-4-failure-isolated-apply-executor.md] — source pattern for `collect_all`'s per-camera try/except isolation

## Dev Agent Record

### Agent Model Used

claude-sonnet-5

### Debug Log References

- Real `cctv status cameras.yaml` run against the 4-camera fleet immediately surfaced a cosmetic bug: action rules without `pre_duration`/`post_duration` params (e.g. the M3005's pre-existing `ACC_LED_NetworkShare` LED-control rule, unrelated to motion recording) printed as `pre Nonems, post Nonems`. Fixed by rendering `None` durations as `n/a` in `reporter.print_camera_status`.
- Real run also correctly showed `smb share: None:None (user: None)` for 192.168.1.72 (the M3085-V) — confirmed this is accurate, not a bug: that camera was configured manually per `AXIS_CAMERA_SETUP_MANUAL.md`'s SD+SFTP workflow and genuinely has no `root.NetworkShare` (N0) configured. The status report correctly reflects live camera state even when it diverges from what `cctv apply` would normally set up.
- Em dashes ("—") in output render as "�" on the operator's Windows console (cp1252 codepage) — pre-existing behavior shared with `print_apply_results`' `FAILED — <reason>` line, not introduced by this story; not fixed here as it's a console-encoding issue orthogonal to this story's scope.

### Completion Notes List

- Preparatory refactor: promoted `parse_motion_windows`, `find_full_frame_window_id`, `full_frame_sensitivity_key`, `find_vmd_app`, `VMD_APP_NAMES`, `VMD_NICE_NAME` from private to public in `reconciler.py`. No behavior change; confirmed zero test breakage (not referenced by name in any existing test).
- New `src/cctv/status.py`: `CameraStatusResult`/`ActionRuleStatus` dataclasses, `collect_status` (GET-only, reuses the promoted reconciler helpers instead of re-deriving motion/app-matching logic), `collect_all` (per-camera failure isolation mirroring `executor.apply_all`, catches broad `Exception` not just `VapixError` — matches the established pattern). 100% test coverage, zero calls to any write endpoint (asserted directly in `test_collect_status_never_calls_any_write_function`).
- `reporter.print_camera_status` added; `cli.py` gets a new `status` command. Caught and fixed a naming bug before it shipped: naming the Typer command function `status` shadowed the imported `status` module at module scope, which would have made `status.collect_all(...)` raise `AttributeError` at runtime. Fixed the same way `list`/`list_cameras` already handles this: function named `camera_status`, registered as `@app.command(name="status")`.
- Verified end-to-end against the real 4-camera fleet (192.168.1.57, .60, .72, .79) — all report correctly, exit code 0, zero write calls made (confirmed by code inspection + the fact that no camera state changed as a side effect of running `status` repeatedly).
- 165 pytest tests pass (27 new: 10 in `test_status.py`, 8 in `test_reporter.py`, 8 in `test_cli.py`, 1 rename-safety check), 0 regressions across Epics 1–3 and Story 3.6.

### File List

- src/cctv/reconciler.py (rename refactor)
- src/cctv/status.py (new)
- src/cctv/reporter.py
- src/cctv/cli.py
- tests/test_status.py (new)
- tests/test_reporter.py
- tests/test_cli.py
