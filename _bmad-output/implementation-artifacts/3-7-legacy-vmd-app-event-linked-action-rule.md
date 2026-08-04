# Story 3.7: Legacy VMD App Event-Linked Action Rule

Status: done

## Story

As a home sysadmin,
I want the motion-detection action rule on a legacy camera to trigger from the installed AXIS Video Motion Detection app's own event, not from a fixed built-in motion topic,
So that recordings actually fire on cameras where `root.Motion` is only populated because Story 3.6 installed the app, instead of the rule silently assuming a built-in motion topic that may not apply to that app/firmware combination.

## Acceptance Criteria

1. **Given** `cctv apply` found the AXIS Video Motion Detection app already installed or had to install it this run (i.e. the camera needed the app to expose motion at all — the Story 3.6 install path), **when** the motion detection action rule is created or updated, **then** the rule's condition topic targets the installed app's own event topic, not the generic window-based `tns1:VideoAnalytics/tnsaxis:MotionDetection` topic used for cameras with native built-in motion.
2. **Given** a camera exposes `root.Motion` natively and never required the VMD app install step (built-in motion detection, per Story 3.1/3.3), **when** the motion detection action rule is created or updated, **then** the existing window-based topic behaviour is unchanged.
3. **Given** the exact event topic string published by `AXIS_Video_Motion_Detection_2_2_1.eap` was not confirmed against real hardware at design time, **when** this story is implemented, **then** the topic constant is added marked `UNVERIFIED` and the story does not move to `done` until a real camera confirms it.
4. **Given** a camera already has a pre-Story-3.7 rule on the built-in topic with durations that happen to match config, **when** `cctv apply` runs against it after this story, **then** the rule is migrated to the legacy app topic (topic mismatch alone is sufficient to trigger remove+recreate — matching durations must not be treated as "already configured" when the topic itself is wrong).
5. **Given** `cctv status` runs against a camera with a motion app installed, **when** the report is printed, **then** it states whether motion is driven by the legacy `.eap` app or a built-in VMD app, not just the raw package name.

## Hardware Verification (2026-07-25 through 2026-08-03, real fleet: 192.168.1.57 / .60 / .72 / .79)

This story's premise changed twice under real-hardware testing — recorded here because both turns are instructive:

1. **First guess was wrong.** The original UNVERIFIED topic (`tnsaxis:CameraApplicationPlatform/VideoMotionDetection/Camera1Profile1`, modelled on the VMD4 pattern in AXIS_CAMERA_SETUP_MANUAL.md §5.4) does not exist on this firmware. `GetEventProperties` against the real M3005 (192.168.1.60) showed no such topic.
2. **`GetEventProperties` schema-matching was also misleading.** It showed the *existing* built-in topic (`tns1:VideoAnalytics/tnsaxis:MotionDetection`, Source=`window`, Data=`motion`) has a schema that exactly matches what `root.Motion` windows produce — which looked like proof the built-in topic was already correct for the legacy-app case too. It wasn't a reliable signal: schema-matching is not the same as confirming what the app's own trigger option actually publishes.
3. **Ground truth came from the camera's own UI**, not from inference: manually editing the `cctv_motion_record` rule in 192.168.1.60's web UI to select trigger "Applications → VideoMotionDetection" (as opposed to the built-in "Detectors" trigger) and reading back the result via `GetActionRules` gave the real topic:
   - Topic: `tns1:RuleEngine/tnsaxis:VideoMotionDetection/motion` (camera echoes it with a trailing `//.`, which `AddActionRule` does not require — matches the pre-existing built-in topic constant's convention of omitting it)
   - Filter: `boolean(//SimpleItem[@Name="active" and @Value="1"]) and boolean(//SimpleItem[@Name="areaid" and @Value="0"])` — `areaid` is the app's own polygon-area index (configured via its `local/VideoMotionDetection/setup.shtml` UI, not `root.Motion`), area `0` being its default/only area on this hardware.
4. **`cctv status` (real fleet, 2026-08-03) surfaced a second real bug**: `.57` and `.79` — both running the legacy app — still had their *original* rule on the built-in topic, because `_ensure_motion_action_rule`'s "already configured" check only compared name/durations/storage, never the topic. A plain `cctv apply` re-run would never have migrated them. Fixed by moving topic/filter selection before the existing-rule scan and requiring `rule.topic.startswith(topic)` as part of "already configured" (AC4). Confirmed fixed against the real fleet's stale rules (see Deferred/regression test).
5. **`cctv status` output enhancement (AC5)**: added a `motion_source` field (`"legacy app (.eap)"` / `"built-in"` / `None`) so the report states the distinction directly instead of making the operator infer it from a raw package `Name`. Verified against the live fleet: `.57`/`.60`/`.79` (M3005/P1204, legacy `.eap`) show `[legacy app (.eap)]`; `.72` (M3085-V, VMD4 `vmd` package) shows `[built-in]`.

## Post-done cleanup (2026-08-03, same day)

Two follow-up fixes to the `cctv status` display, prompted by using the tool against the real fleet immediately after this story:

1. **"no app installed" wasn't flagged as wrong.** `cctv` always requires a VMD app for motion (built-in `vmd` or legacy `.eap`) — there's no third "no app" mode. `reporter.py`'s `motion app:` line now reads `NOT INSTALLED — motion detection requires either the built-in VMD app or a legacy .eap (see motion_detection.app_package_path)` instead of a neutral `not installed`.
2. **A motion window exists for both detection methods, but only one was displayed.** The built-in VMD3/VMD4 app doesn't use `root.Motion` at all (confirmed empty on the real M3085-V, 192.168.1.72) — its window is a profile/include-area, readable only via its own JSON API (`local/vmd/control.cgi`, VERIFIED against that camera). Added `vapix.get_vmd4_profiles()` and wired it into `status.py` as a fallback when `root.Motion` is empty and the installed app is the built-in one — `cctv status` now shows `profile(s): Profile 1` for VMD4 cameras instead of misreporting "no window configured". `motion_sensitivity` stays `None` for this path (VMD4 has no single 0–100 knob, per AXIS_CAMERA_SETUP_MANUAL.md §2 — filter-based instead), and `reporter.py` omits the "sensitivity" phrase when it's `None`.

New: `ActionRuleStatus`/`CameraStatusResult` gained `motion_window_detail: Optional[str]` (status.py now owns the human-readable window/profile description; reporter.py just displays it — same split as `motion_source`/`motion_rule_mismatch`). 8 new tests across `test_vapix.py`/`test_status.py`/`test_reporter.py`; 2 existing tests updated for the new wording/fields. Full suite: 188 passed.

~~Still not covered: the legacy `.eap`'s own polygon-area config has no known VAPIX read path.~~ **Resolved same day (2026-08-04).** Found `GET /axis-cgi/vaconfig.cgi?action=get&name=VideoMotionDetection` by reading `local/VideoMotionDetection/setup.shtml`'s own JavaScript (`loadAppConfig()`, `configCGI = "/axis-cgi/vaconfig.cgi"`) — the setup page itself is IE/ActiveX-only and unusable directly, and the `/sm/sm.srv` form action turned out to be the *save* path, not read. Queried against all 3 real legacy units (192.168.1.57/.60/.79): **all three return an identical factory-default "Detection Area" polygon (~60% width × 60% height, centered) at `areaid=0`** — confirming `_LEGACY_VMD_APP_MOTION_FILTER`'s hardcoded `areaid="0"` is correct, but also revealing that **this polygon area, not `root.Motion`, is what actually feeds the migrated action rule** — `root.Motion`'s windows/sensitivity (still real, still written by `cctv apply`'s reconciler, Story 3.1/3.3) describe a wholly separate, rule-irrelevant configuration surface once the topic is migrated. Added `vapix.get_vmd_app_config()`; `status.py` now shows the app's real area for legacy cameras (`app area: 'Detection Area' 60% x 60% area`) instead of `root.Motion`-derived numbers. `motion_sensitivity` is `None` for this path — the app's own config has no 0–100 knob (boolean filter flags + an encrypted `detection.lua` script instead).

~~Still open: the polygon is a fixed ~60%-centered square on every camera tested — smaller than the full frame `cctv apply` was previously configuring via `root.Motion`.~~ **Resolved same day (2026-08-04) — `cctv apply` now manages this.**

## Write support: `cctv apply` now expands the app's own area to full-frame (2026-08-04, same day)

Found the write path by reading the same `setup.shtml` JS further (`uploadAppConfig()`): `GET` the current `<config>` XML, surgically replace `<namedObjects>` and the `<rule>`'s `Include` parameters (leaving `<scripts>`/`<events>`/`<moteConfig>` untouched), `POST` the whole modified document back to the same URL as a raw (non-form-encoded) `action=modify&name=<app>\n<xml>` body. The `<form action="/sm/sm.srv">` in the HTML is a red herring — the real save button calls `uploadAppConfig()` directly, bypassing that form.

**VERIFIED end-to-end against a real AXIS M3005 (192.168.1.60):** expanded the factory-default ~60% polygon to full-frame (`(1,1),(1,-1),(-1,-1),(-1,1)`) via an ad-hoc script, read it back to confirm it persisted, then ran the real `cctv apply` (after wiring it into `reconciler.py`) against the whole fleet: **`.57` and `.79` both reported `applied (motion_app_area)`; `.60` correctly reported `no change` (idempotent — already full-frame from the earlier manual test); `.72` (built-in VMD4) untouched, as designed.** `cctv status` confirms all three legacy cameras now show `100% x 100% area (cctv-managed, full-frame)`.

- `vapix.py`: added `set_vmd_app_config()` — read-modify-write, same conventions as `get_vmd_app_config`.
- `reconciler.py`: added `_LEGACY_VMD_APP_AREA_NAME`/`_LEGACY_VMD_APP_FULL_FRAME_POINTS` constants, `_vmd_app_area_is_full_frame()`, `_ensure_vmd_app_area()` — called right after `_ensure_motion_app_installed`, gated on `vmd_app.name == _LEGACY_VMD_APP_NAME` (never touches built-in `vmd`/VMD4 cameras, which use a different, unexplored config mechanism). Appends `"motion_app_area"` to `settings_changed` when a change is made.
- `status.py`: app-area display now tags `(cctv-managed, full-frame)` when already converged, same convention as the `root.Motion` window tagging added earlier.
- New tests: `test_vapix.py` (6 for `set_vmd_app_config`), `test_reconciler.py` (4 for the new reconcile step + a new `default_vmd_area_mocks` autouse fixture defaulting to already-full-frame so pre-existing legacy-app tests don't unexpectedly trigger writes). Full suite: 212 passed.

**Known limitation, not fixed:** only handles single/multiple `Include`-type areas — no `Exclude`-area support (none observed on any of the 3 real units). If an operator manually adds an Exclude zone via the (barely usable, IE-only) app UI, the next `cctv apply` would silently drop it when rewriting `namedObjects`.

## Write support extended to the built-in VMD3/VMD4 app too (2026-08-04, same day)

User asked to check whether `.72` (AXIS M3085-V, built-in `vmd` app) has an *official* API for this, unlike the legacy app's reverse-engineered one — it does. `local/vmd/control.cgi`'s `getConfiguration`/`setConfiguration` methods are Axis's own documented VMD4 JSON control API (confirmed via `getSupportedVersions` and `setConfiguration` returning error code `2003` "mandatory parameter missing" rather than `2005` "method not found" — i.e. the method is recognized). One real quirk found only empirically (undocumented anywhere accessible): the request payload key is **`"params"`, not `"data"`** — sending it under `"data"` returns HTTP 200 with no error and silently does nothing.

**VERIFIED end-to-end against the real AXIS M3085-V (192.168.1.72, firmware 12.11.72):** the default profile shipped covering only ~97% of the frame (not full) — expanded its `includeArea` trigger to `(-1,-1)-(1,1)` via an ad-hoc script using the `"params"` key, read back via `getConfiguration` to confirm it persisted (`configurationStatus` incremented, `includeArea` data changed, `filters`/`uid`/`name` untouched). `cctv status` confirms: `profile(s): Profile 1` → after the fix, area is full-frame.

- `vapix.py`: added `get_vmd4_configuration()`/`set_vmd4_configuration()` — unlike `get_vmd4_profiles` (typed, read-only, used for display), these work with the opaque raw `data` dict for round-trip read-modify-write, mirroring the legacy app's `get_vmd_app_config`/`set_vmd_app_config` pattern (preserve what isn't understood/touched).
- `reconciler.py`: added `_VMD4_FULL_FRAME_AREA`, `_vmd4_profile_is_full_frame()`, `_ensure_vmd4_full_frame_area()` — wired into the same call site as the legacy path, branching on `vmd_app.name` (legacy → `_ensure_vmd_app_area`, built-in → `_ensure_vmd4_full_frame_area`). Both share the `"motion_app_area"` `settings_changed` label — same semantic ("the app's own detection area was expanded to full-frame"), different underlying API.
- `tests/test_reconciler.py`: new `default_vmd4_area_mocks` autouse fixture (defaults to already-full-frame, mirroring `default_vmd_area_mocks` for the legacy path) + 4 new tests. `tests/test_vapix.py`: 6 new tests, including one specifically pinning the `"params"` (not `"data"`) key regression.
- Full suite: 221 passed.

**Not exercised end-to-end through the real `cctv apply` code path** (only via the ad-hoc script + mocked unit tests) — `.72` fails earlier in `reconcile()`'s sequence on an unrelated, expected SMB error (that camera is on a different network segment; its SMB share is genuinely unreachable from it, confirmed by the operator — not a bug). If `.72`'s SMB config is ever fixed/skipped, worth re-running `cctv apply` once to confirm the VMD4 area step actually fires through the full pipeline, not just the isolated write function.

## Tasks / Subtasks

- [x] Add `_LEGACY_VMD_APP_NAME`, `_BUILTIN_MOTION_TOPIC`, `_LEGACY_VMD_APP_MOTION_TOPIC`, `_LEGACY_VMD_APP_MOTION_FILTER` constants to `src/cctv/reconciler.py` — VERIFIED on firmware 5.51.7.4 against 192.168.1.60 (AC: 1, 2, 3)
- [x] `_ensure_motion_app_installed` returns `(change_label, app)` instead of just `change_label`, so `reconcile()` knows which app (built-in `"vmd"` vs legacy `"VideoMotionDetection"`) is backing motion on this camera, even on a no-change run (AC: 1)
- [x] `_ensure_motion_action_rule` takes `use_legacy_app_topic: bool = False`; topic/filter selection moved *before* the existing-rule scan so a pre-existing rule is checked against the topic the camera should have right now, not just durations (AC: 1, 2, 4)
- [x] `reconcile()` computes `use_legacy_app_topic = vmd_app is not None and vmd_app.name == _LEGACY_VMD_APP_NAME` and passes it through (AC: 1, 2)
- [x] `status.py`: added `CameraStatusResult.motion_source`, computed in `collect_status` the same way as `use_legacy_app_topic` above (local `_LEGACY_VMD_APP_NAME` re-declared per this module's established constant-duplication convention) (AC: 5)
- [x] `reporter.py`: `print_camera_status` appends `[<motion_source>]` after the app status line when set (AC: 5)
- [x] Tests — `tests/test_reconciler.py`, `tests/test_status.py`, `tests/test_reporter.py` (AC: all)
  - [x] `test_reconcile_legacy_vmd_app_uses_app_event_topic` / `test_reconcile_builtin_vmd_app_uses_builtin_topic` / `test_reconcile_newly_installed_legacy_app_uses_app_event_topic` (AC 1, 2)
  - [x] `test_reconcile_legacy_app_migrates_existing_builtin_topic_rule` — regression test for the real-fleet `.57`/`.79` finding (AC 4)
  - [x] `default_soap_mocks` autouse fixture extended to mock `remove_action_rule`/`remove_action_configuration` (previously only `add_*`) — needed once the migration path could actually trigger for tests not specifically exercising action-rule content
  - [x] `test_collect_status_motion_source_legacy_app` / `_built_in` / `_none_when_no_app` (AC 5)
  - [x] `test_print_camera_status_motion_source_shown` / `_no_motion_source_no_brackets` (AC 5)
- [x] Full `pytest` run — 174 passed, 0 regressions
- [x] Hardware verification — topic/filter confirmed via camera UI + `GetActionRules` readback (192.168.1.60); migration fix confirmed against real stale rules on `.57`/`.79`; `motion_source` label confirmed against all 4 real cameras (`.57`, `.60`, `.72`, `.79`)

## Dev Notes

### Why this exists

Story 3.6 (hardware-verified) found that on a legacy AXIS M3005, `root.Motion` is empty until the 2.2.1 `.eap` is installed and started — the window/sensitivity config in Story 3.1/3.3 only works *because* the app is running. But the action rule that turns a motion event into a recording (Story 3.1) was always wired to a single hardcoded topic regardless of which underlying app (if any) produces that motion. `AddActionRule` doesn't validate that a topic will ever actually fire — a syntactically valid but wrong topic makes `cctv apply` report success while motion silently never triggers a recording.

### VERIFIED topic/filter (see Hardware Verification above for how these were obtained)

```python
_LEGACY_VMD_APP_MOTION_TOPIC = "tns1:RuleEngine/tnsaxis:VideoMotionDetection/motion"
_LEGACY_VMD_APP_MOTION_FILTER = 'boolean(//SimpleItem[@Name="active" and @Value="1"]) and boolean(//SimpleItem[@Name="areaid" and @Value="0"])'
```

`areaid="0"` is hardcoded to the app's default/only polygon area on the hardware tested. `cctv` has no VAPIX read path for the app's own area configuration (only for `root.Motion` windows), so a camera whose app is manually reconfigured with additional/non-zero-indexed areas would need this to become dynamic — flagged in deferred-work.md, not fixed here.

### Backward-compatible with existing rule detection

`_ensure_motion_action_rule`'s existing-rule matching loop already checked for `"VideoMotionDetection" in rule.topic` as well as `"MotionDetection"` (pre-existing code). `_LEGACY_VMD_APP_MOTION_TOPIC` contains that substring, so this remains correct without touching that first-pass filter — the AC4 fix only added a second, stricter check (`rule.topic.startswith(topic)`) inside it.

### Architecture Constraints — unchanged from prior Epic 3 stories

- `import requests` FORBIDDEN outside `vapix.py`
- `print()` FORBIDDEN outside `reporter.py`
- `config.timeout` always — never hardcode
- Patch at `cctv.reconciler.vapix.*` / `cctv.status.vapix.*` in tests, not `cctv.vapix.*`

### Files Modified

- `src/cctv/reconciler.py` — new constants, `_ensure_motion_app_installed` return type, `_ensure_motion_action_rule` topic-aware matching
- `src/cctv/status.py` — `motion_source` field + computation
- `src/cctv/reporter.py` — `motion_source` display
- `tests/test_reconciler.py`, `tests/test_status.py`, `tests/test_reporter.py` — new/updated tests

### References

- [epics.md#Story 3.7] — acceptance criteria, FR35
- [3-6-legacy-camera-vmd-app-detection-and-install.md] — install path this story keys off of; hardware-verification precedent
- [AXIS_CAMERA_SETUP_MANUAL.md#section 5.4] — `CameraApplicationPlatform/<app>/<profile>` topic pattern (VMD4) that motivated (and turned out not to match) the first guess
- [deferred-work.md#Deferred from code review of 3-7] — open follow-ups (hardcoded `areaid="0"`, no real-motion-triggered recording confirmation yet — only event-topic/rule-config confirmed, not an actual file landing on the NetworkShare)
