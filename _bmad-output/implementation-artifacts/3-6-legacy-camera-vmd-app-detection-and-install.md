# Story 3.6: Legacy Camera VMD App Detection and Install

Status: done

## Story

As a home sysadmin,
I want the tool to detect whether the AXIS Video Motion Detection app is installed on a camera and install it from a local `.eap` package if it's missing,
So that motion detection can be configured on legacy cameras that don't ship with the app pre-installed, without a manual VAPIX/SOAP workaround per camera.

## Acceptance Criteria

1. **Given** `motion_detection.enabled: true` in config and the AXIS Video Motion Detection app is not present in the camera's installed-applications list, **when** `cctv apply` runs and `motion_detection.app_package_path` is set in config, **then** the `.eap` file at that path is uploaded and installed via VAPIX, the app is started using whatever package `Name` the camera actually assigns it (not a fixed constant — different `.eap` versions register under different internal names), and `"motion_app_installed"` is included in `CameraResult.settings_changed`.
2. **Given** the app is not installed and `motion_detection.app_package_path` is not set, **when** `cctv apply` runs, **then** a clear `VapixError` is raised naming the camera IP and the missing config key, and no upload is attempted.
3. **Given** the app is already installed but its Status is `"Stopped"`, **when** `cctv apply` runs, **then** the app is started via VAPIX (not re-uploaded) and `"motion_app_started"` is included in `CameraResult.settings_changed`.
4. **Given** the app is already installed and its Status is anything other than `"Stopped"` (e.g. `"Running"` or `"Idle"`), **when** `cctv apply` runs, **then** no install or start call is made, and the run is idempotent.

## Tasks / Subtasks

- [x] Add `motion_detection.app_package_path` optional config key (AC: 1, 2)
  - [x] `CameraConfig.motion_app_package_path: Optional[str] = None` in `src/cctv/config.py`
  - [x] Loaded from YAML `motion_detection.app_package_path`, defaults to `None`
  - [x] Documented in `cameras.yaml.example`; set in the operator's real `cameras.yaml`
- [x] Add VAPIX application-management helpers to `src/cctv/vapix.py` (AC: 1, 3)
  - [x] `InstalledApplication` dataclass (`name`, `nice_name`, `status`)
  - [x] `get_applications()` — GET `axis-cgi/applications/list.cgi`, parse `<application Name=... NiceName=... Status=.../>` tags
  - [x] `upload_application()` — POST `.eap` file to `axis-cgi/applications/upload.cgi` (multipart field `packfil`)
  - [x] `start_application()` — GET `axis-cgi/applications/control.cgi?action=start&package=<name>`
- [x] Add `_ensure_motion_app_installed` reconciler step, run before the existing motion window logic whenever `motion_enabled` (AC: 1, 2, 3, 4)
  - [x] Match installed app by `name in ("vmd", "VideoMotionDetection")` or `nice_name == "AXIS Video Motion Detection"` — not a single hardcoded name (see Dev Notes — Hardware Verification)
  - [x] Not found + no `app_package_path` configured → raise `VapixError` naming the camera IP and missing config key (AC: 2)
  - [x] Not found + `app_package_path` configured → upload, re-list to discover the real assigned package `Name`, then start under that name; append `"motion_app_installed"` (AC: 1)
  - [x] Found with `Status == "Stopped"` → start under its existing `name`; append `"motion_app_started"` (AC: 3)
  - [x] Found with any other status (`Running`, `Idle`, ...) → no action (AC: 4)
- [x] Tests: `tests/test_vapix.py`, `tests/test_config.py`, `tests/test_reconciler.py`, `tests/conftest.py` (all AC)
- [x] Hardware verification against 2 real AXIS M3005 cameras (see Dev Notes — Hardware Verification)
- [x] Run `pytest` — all tests pass, no regressions

## Dev Notes

### What Already Exists — Built On, Not Reimplemented

Story 3.3 built the motion window/sensitivity/action-rule reconciler logic in `reconciler.py`. This story adds a new step that runs *before* that logic, gated on the same `config.motion_enabled` flag. It does not touch the window/sensitivity/action-rule code.

### Hardware Verification — Real Findings (Critical)

This story was implemented and verified against real hardware (2x AXIS M3005 on the operator's subnet, package `AXIS_Video_Motion_Detection_2_2_1.eap`). Two assumptions from the first implementation pass were **wrong** and had to be corrected after real `cctv apply` runs failed:

1. **Package `Name` is NOT `"vmd"` for every `.eap` version.** The legacy 2.2.1 package installs under `Name="VideoMotionDetection"`; only VMD3/VMD4 use `Name="vmd"` (per `AXIS_CAMERA_SETUP_MANUAL.md` section 1). Calling `start_application(..., "vmd")` against a freshly-installed 2.2.1 package failed with `Error: 4` (package not found) even though the upload itself succeeded. **Fix:** re-list applications after upload and start whichever `Name` the camera actually assigned; match existing apps by name-or-nice-name, never a hardcoded constant.
2. **A successfully started legacy app reports `Status="Idle"`, not `"Running"`.** The first fix attempt used `if app.status != "Running": start(...)`, which caused `start_application` to fire on every single reconcile against the real cameras — breaking idempotency (FR16). **Fix:** only `Status == "Stopped"` triggers a start call. This matches what `AXIS_CAMERA_SETUP_MANUAL.md` section 2 already documented for the `vmd` app ("If the vmd application shows Status='Stopped' ... start it") — the manual had the right condition; the first implementation attempt deviated from it.

Both bugs were caught only by running `cctv apply` against real cameras — the mocked test suite was green throughout because it was written to match the (wrong) assumptions. Future VAPIX-integration stories should budget a real-hardware verification pass before marking the story done, not rely on mocked tests alone.

### VAPIX Application API — Endpoint Notes

- `GET axis-cgi/applications/list.cgi` — verified against real M3005 hardware. Response: `<reply result="ok"><application Name="..." NiceName="..." Status="Running|Stopped|Idle"/>...</reply>`.
- `GET axis-cgi/applications/control.cgi?action=start&package=<name>` — verified (matches the manual's existing `vmd` case; confirmed again here with `VideoMotionDetection`).
- `POST axis-cgi/applications/upload.cgi` with multipart field `packfil` — **worked** against the real M3005 both times it was exercised this session, but the field name was chosen from general VAPIX Application API convention, not confirmed against Axis's written docs for this specific endpoint. Treat as verified-by-successful-case, not exhaustively confirmed across firmware/models — see Review Findings.

### Key Implementation Detail — Two-Phase Install

```python
apps = vapix.get_applications(ip, auth, timeout)
app = _find_vmd_app(apps)  # match by name in ("vmd", "VideoMotionDetection") or nice_name

if app is None:
    if not config.motion_app_package_path:
        raise VapixError(...)
    vapix.upload_application(ip, auth, timeout, config.motion_app_package_path)
    apps = vapix.get_applications(ip, auth, timeout)  # re-list — Name unknown until now
    app = _find_vmd_app(apps)
    if app is None:
        raise VapixError(...)  # uploaded but didn't register — surface, don't silently continue
    vapix.start_application(ip, auth, timeout, app.name)
    return "motion_app_installed"

if app.status == "Stopped":
    vapix.start_application(ip, auth, timeout, app.name)
    return "motion_app_started"

return None
```

### Architecture Constraints — CRITICAL (unchanged from prior Epic 3 stories)

- `import requests` FORBIDDEN outside `vapix.py`
- `print()` FORBIDDEN outside `reporter.py`
- `config.timeout` always — never hardcode
- `VapixError` MUST propagate from `reconcile()` — `executor.py` is the failure-isolation boundary
- Patch at `cctv.reconciler.vapix.*` in reconciler tests, not `cctv.vapix.*`

### Fixture Pattern — Default Autouse Mock

Adding a network call inside `reconcile()` that every existing test would otherwise hit for real required a new autouse fixture (`default_vmd_app_mocks` in `test_reconciler.py`) returning a healthy `InstalledApplication(name="vmd", status="Running")` by default, so pre-existing tests didn't need per-test changes. Tests exercising install/start override it explicitly. Same pattern as the pre-existing `default_soap_mocks` autouse fixture for action rules.

### Files to Create / Modify

- `src/cctv/vapix.py` — MODIFY (add `InstalledApplication`, `get_applications`, `upload_application`, `start_application`)
- `src/cctv/config.py` — MODIFY (add `motion_app_package_path`)
- `src/cctv/reconciler.py` — MODIFY (add `_find_vmd_app`, `_ensure_motion_app_installed`, call site before motion window step)
- `cameras.yaml.example`, `cameras.yaml` — MODIFY (document/set `app_package_path`)
- `tests/conftest.py`, `tests/test_vapix.py`, `tests/test_config.py`, `tests/test_reconciler.py` — MODIFY

### References

- [epics.md#Story 3.6] — acceptance criteria, FR28
- [AXIS_CAMERA_SETUP_MANUAL.md#section 1-2] — `vmd` package-name precedent for VMD3/VMD4; `Status="Stopped"` start-trigger precedent
- [3-3-motion-detection-configuration-via-vapix.md] — existing motion reconciler step this one runs ahead of
- [deferred-work.md#Deferred from code review of 3-6] — open follow-ups from this story

## Dev Agent Record

### Agent Model Used

claude-sonnet-5

### Debug Log References

- First `cctv apply` run against real AXIS M3005 units (192.168.1.60, 192.168.1.79): both `FAILED` — `START application vmd on <ip> rejected: Error: 4`. Root cause: package registered as `Name="VideoMotionDetection"`, not `"vmd"`.
- Second run (after fix #1): both `applied (motion_app_installed)`. A follow-up read-only check showed `Status="Idle"`, not `"Running"`, on both — flagged as a latent idempotency bug before it caused repeated writes in production use.
- Third run (after fix #2): both `no change` — confirmed idempotent.

### Completion Notes List

- Implemented, tested (138 pytest tests passing, 0 regressions), and verified end-to-end against 2 real AXIS M3005 cameras (install → start → idempotent re-run).
- Two implementation bugs found only via real-hardware testing (see Dev Notes — Hardware Verification); both fixed and covered by regression tests (`test_reconcile_installs_vmd_app_when_absent`, `test_reconcile_vmd_app_idle_status_no_change`).
- No CLI-level way to scope `apply` to a subset of cameras (e.g. only legacy models) existed at the time of hardware verification — the verification run used an ad-hoc script filtering `scanner.scan()` results by model rather than a supported CLI flag; logged in deferred-work.md.

### File List

- src/cctv/vapix.py
- src/cctv/config.py
- src/cctv/reconciler.py
- cameras.yaml.example
- cameras.yaml
- tests/conftest.py
- tests/test_vapix.py
- tests/test_config.py
- tests/test_reconciler.py

### Review Findings

- [ ] [Defer] `upload_application`'s `packfil` multipart field name is confirmed working against one real M3005 + one `.eap` version this session, but not verified against Axis's written docs or other models/firmware — if uploads start failing on a different camera, check this first.
- [ ] [Defer] No CLI flag to scope `apply`/`list` to a subset of discovered cameras (by model, IP, or tag) — real-hardware verification for this story required an ad-hoc script instead of a supported command. Would benefit future staged-rollout use cases beyond just this story.
- [ ] [Defer] `_find_vmd_app` matches by a fixed tuple of known package names plus one known `NiceName`. A future `.eap` version registering under yet another `Name`/`NiceName` combination would silently fail to match and could trigger a duplicate install attempt. No dynamic/fuzzy discovery mechanism exists.
- [ ] [Defer] `upload_application`/`start_application` error-body detection uses `"error" in resp.text.lower()` — same class of loose string-matching as pre-existing patterns in this codebase (e.g. `set_params`'s `# Error:` check); only two real error strings have been observed (`"Error: 4"`, generic `"Error: ..."`), not hardware-verified across other failure modes.
