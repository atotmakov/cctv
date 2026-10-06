# Deferred Work

## Deferred from: code review of 1-1-project-scaffold-and-installable-cli (2026-04-01)

- `config` Path argument has no existence check — Typer can validate with `exists=True`; deferred to Story 1.3 (config validation)
- No CIDR validation on `--subnet` argument — invalid strings propagate silently; deferred to Story 1.3 (config validation)
- `.gitignore` only catches root-level `cameras.yaml` — nested placements not covered; very low risk since cameras.yaml is conventionally placed at root

## Deferred from: code review of 1-2-yaml-config-file-loading (2026-04-01)

- `load_config` raises bare `KeyError`/`FileNotFoundError` instead of `ConfigError` — deferred to Story 1.3 (config validation)
- `bool('false') == True` for YAML quoted string instead of boolean — still open (Story 1.3 did not address)
- `timeout: null` (explicit null value) → `int(None)` TypeError — deferred to Story 1.3
- `yaml.safe_load` returns `None` for empty/null file — **resolved in Story 1.3** (`isinstance(data, dict)` guard)

## Deferred from: code review of 1-3-config-validation-with-actionable-error-reporting (2026-04-01)

- `motion_detection.sensitivity` non-integer string (e.g. `"high"`) causes bare `ValueError` from `int()` rather than `ConfigError` — deferred to Story 3.3 or a future hardening pass

## Deferred from: code review of 1-4-vapix-api-client-get-and-set-parameters (2026-04-02)

- Plaintext `http://` used for all VAPIX calls — response bodies unencrypted; pre-existing architectural decision (architecture.md NFR8 specifies Digest Auth only, not TLS); revisit post-MVP if tool is used on untrusted networks
- `_parse_param_response` does not detect VAPIX application-level error bodies in HTTP 200 OK (e.g. `# Error: Access denied`) — returns `{}` or partial dict silently; requires hardware verification of exact Axis firmware 5.51.7.4 error format before fixing; flag for Stories 3.2/3.3
- `ip` parameter not validated before URL interpolation — IPs generated from validated CIDR scan so low real-world risk; `ipaddress.ip_address(ip)` guard could be added in a hardening pass

## Deferred from: code review of 2-1-concurrent-axis-camera-discovery (2026-04-02)

- No `root.Brand.Brand == "AXIS"` check in `_probe_ip` — any host responding to VAPIX brand probe is reported as an Axis camera; in practice non-Axis devices won't speak VAPIX, but a strict brand check would be more correct; defer to hardware validation / Story 3.x hardening pass
- `HTTPDigestAuth` instance shared across all worker threads — digest auth maintains nonce/nonce_count state; concurrent requests to different IPs each get different server nonces so practical impact is low, but a race on `nonce_count` is theoretically possible; fix requires passing `(username, password)` to `_probe_ip` and constructing per-probe auth; defer to hardening pass
- Non-`VapixError` exceptions (e.g. encoding errors in `_parse_param_response`) could propagate through `pool.map` and crash the entire scan — theoretical after Story 1.4 patches wrap all known exceptions in `VapixError`; add broad catch in `_probe_ip` if observed in practice
- `timeout=0` or negative not validated in scanner — `load_config` is the config boundary; acceptable for now
- `max_workers=50` hard-coded — unconfigurable; revisit if /24 scan performance is inadequate on constrained hardware

## Deferred from: code review of 2-2-discovery-output-and-subnet-override (2026-04-04)

- `apply` raises bare `NotImplementedError` producing a Python traceback — pre-existing stub (Story 1.1); will be replaced when Epic 3 implements the command
- Exit code 2 is used for both `ConfigError` and no-cameras-found in `list_cameras` — conflated failure modes; pre-existing from Story 1.3; revisit in Epic 3 when exit code contract is firmed up
- `scanner.scan` exceptions propagate uncaught through `list_cameras` — scanner catches `VapixError` internally so low real-world risk; add broad catch if other exceptions observed in practice
- `effective_subnet or cfg.subnet` silently accepts empty-string subnet from config — config.py validation gap from Story 1.2; guard with `ip_network` check in a future hardening pass
- No integration test for invalid `--subnet` CIDR via CLI — `_validate_subnet` exists but error path untested end-to-end; add test in a hardening pass
- No test covering AC1 "no configuration changes" constraint for `cctv list` — would require deeper integration test verifying no write/apply calls made; defer to integration test story
- `motion_sensitivity` range not validated (accepts values outside 0–100), `password: null` passes key-presence check, empty-string credentials accepted silently, `timeout` not validated positive — config.py gaps from Stories 1.2/1.3; address in a config hardening pass before hardware rollout

## Deferred from: code review of 3-3-motion-detection-configuration-via-vapix (2026-04-04)

- UNVERIFIED motion param constants (`_MOTION_ENABLED`, `_MOTION_SENSITIVITY`, `M0` window index) used in prod and tests — firmware may silently ignore unknown keys, making test-green / prod-broken invisible; hardware verification pass required before production use
- `motion.get()` returns None when key absent — if firmware returns wrong group or missing key, `None != config_str` unconditionally fires SET every run; breaks idempotency silently; depends on hardware verification
- `motion_enabled=False` + camera already `"no"` + sensitivity differs — `or` branch fires on sensitivity alone when enabled is already correct; untested path; add test in hardening pass
- Non-canonical numeric string from camera (e.g., `"050"` for 50) causes spurious SET every run — strict string equality `"050" != "50"`; hardware verification needed to confirm firmware serialization format
- `mock_get.side_effect` ordering implicit contract — all reconciler tests assume exactly 2 `get_params` calls in SMB-first order; a refactor adding a third call would cause `StopIteration` rather than a clear assertion failure; add `mock_get.call_count` assertions in hardening pass

## Deferred from: code review of 3-2-smb-share-configuration-via-vapix (2026-04-04)

- NFR7 test trivially passes — hand-crafted VapixError message never contains password; a stronger test would use a `raising_set` side_effect that embeds its args dict in the error message and then asserts password absent; structural protection (vapix.py never echoes params) remains valid; defer to hardening pass
- SET call order (smb_ip before smb_creds) not enforced by tests — `assert_any_call` doesn't pin ordering; on real hardware ordering may matter (update host before sending credentials); revisit in hardware verification pass
- VapixError from `set_params` call (smb_ip or smb_creds SET raises) untested — pre-existing from Story 3.1; add test where set_params raises to verify propagation behavior
- Empty dict from get_params (factory-reset camera with no SMB group) untested — behavior is correct by logic (None != config value triggers write) but untested; depends on UNVERIFIED param name hardware verification
- VapixError from second (motion) get_params call untested — pre-existing from Story 3.1; add test where smb GET succeeds but motion GET raises
- motion_sensitivity boundary values (0, 100) and float slip-through untested — `str(float)` produces "50.0" not "50"; a float motion_sensitivity in CameraConfig would cause permanent spurious SET loop on real hardware; add int cast guard and boundary tests in hardening pass

## Deferred from: code review of 3-5-per-camera-output-summary-and-exit-codes (2026-04-04)

- `APPLIED` with empty `settings_changed` renders as `applied ()` — not reachable (reconciler returns NO_CHANGE for empty diff); add guard `if settings_changed` in a hardening pass
- `FAILED` with `error=None` renders as `"FAILED — None"` — executor always sets error for FAILED results; pre-existing `Optional[str]` type gap; add guard `result.error or "unknown error"` in hardening pass
- `model=None` interpolated directly in all f-strings — scanner always provides model; pre-existing type gap from architecture.md `Optional[str]` definition; add guard in hardening pass
- `apply` CLI exits 0 with empty-fleet summary when scanner returns no cameras — `list` exits 2 for this case; `apply` has no equivalent guard; add explicit no-cameras handling in a hardening pass
- `typer.echo` in cli.py bypasses reporter.py for ConfigError output — pre-existing from Story 1.3; `typer.echo` is Typer-idiomatic; full reporter delegation would require adding a `print_fatal_error()` function in a hardening pass
- `print_apply_results` iterates results 4× (1 loop + 3 sum() calls) — type-enforced list, no practical impact; could be optimised to single-pass counting in a hardening pass

## Deferred from: code review of 3-4-failure-isolated-apply-executor (2026-04-04)

- `apply` exits 0 even when all cameras FAILED — no exit-code logic for FAILED results; intentional per spec; Story 3.5 owns exit codes and reporting
- `apply` produces no output when cameras fail — reporter.print_apply_results commented out; intentional per spec; Story 3.5 adds reporting
- `str(exc)` may leak credentials from non-VapixError exceptions — architectural enforcement at vapix.py/reconciler.py boundary prevents credentials from appearing in exception messages; broad catch is intentional; add sanitisation in hardening pass if non-VAPIX exceptions are ever observed
- Credentials test uses manually crafted VapixError message not the real vapix.py format — structural protection (vapix.py never echoes params) is valid; add a real-format regression test in hardening pass
- `apply --subnet` override path has no test for apply command — equivalent test exists for `list`; add in a hardening pass
- `DiscoveredCamera.model` always returns a string (falls back to `"Unknown"`) but `CameraResult.model` is typed `Optional[str]` — pre-existing type mismatch; no real-world impact until reporter formats results; address in Story 3.5 or typing hardening pass

## Deferred from: code review of 3-1-read-before-write-state-reconciliation (2026-04-04)

- Empty/absent VAPIX params silently trigger SET calls — `dict.get()` returns None when param key is absent → None != expected value → reconcile always writes; pre-existing UNVERIFIED param risk; Stories 3.2/3.3 own hardware verification and will confirm actual param names/presence
- Partial-apply risk: `set_params` raising VapixError mid-reconcile leaves camera in inconsistent state (some groups written, others not) — by design; executor.py (Story 3.4) is the failure-isolation boundary; Story 3.4 must document this behavior in its error model

## Deferred from: code review of 3-6-legacy-camera-vmd-app-detection-and-install (2026-07-24)

- `upload_application`'s `packfil` multipart field name is confirmed working against one real AXIS M3005 + one `.eap` version (`AXIS_Video_Motion_Detection_2_2_1.eap`), but not verified against Axis's written docs or other models/firmware; if installs fail unexpectedly on a different camera, verify this field name first (see also AXIS_CAMERA_SETUP_MANUAL.md's general "verify with the camera's own API discovery first" guidance)
- No CLI flag to scope `apply`/`list` to a subset of discovered cameras (by model, IP, or tag) — hardware verification for this story required an ad-hoc script filtering `scanner.scan()` results rather than a supported command; would help future staged rollouts (e.g. legacy-only or one-camera-first applies)
- `_find_vmd_app` matches installed apps by a fixed tuple of known package `Name`s (`"vmd"`, `"VideoMotionDetection"`) plus one known `NiceName`; a future `.eap` version registering under a different Name/NiceName combination would silently fail to match, risking a duplicate install attempt instead of a clear error
- `upload_application`/`start_application` error-body detection uses `"error" in resp.text.lower()` — same loose string-matching class as the pre-existing `set_params` `# Error:` check; only two real error strings observed this session (`"Error: 4"`, generic `"Error: ..."`), not hardware-verified across other failure modes
- Pre-existing, noticed while touching this area: `vapix.py`'s `_soap_post` fault detection checks `"<SOAP-ENV:Fault>" in resp.text` twice via `or` (copy-paste — the second clause is a dead no-op); unrelated to this story's changes but flagged here since it wasn't previously in deferred-work.md

## Deferred from: code review of 3-7-legacy-vmd-app-event-linked-action-rule (2026-08-04)

- `_LEGACY_VMD_APP_MOTION_TOPIC`/`_LEGACY_VMD_APP_MOTION_FILTER` are confirmed VERIFIED (camera UI + `GetActionRules` readback against 192.168.1.60), and the rule-migration path was confirmed fixing real stale rules on `.57`/`.79` — but no test in this codebase confirms motion actually landing as a *file* on the NetworkShare; verification stopped at "the camera accepted the topic, the rule config is now correct, and the app's own detection area (via `vaconfig.cgi`) is confirmed non-empty at `areaid=0`" — not an end-to-end real-motion-to-recorded-clip check. Worth closing out if this ever regresses.
- **Resolved (2026-08-04):** `areaid="0"` was previously unverifiable (no known read path). Found `axis-cgi/vaconfig.cgi?action=get&name=<app>` (undocumented — found by reading the app's setup page JS) and confirmed all 3 real legacy units use `areaid=0` for their one and only "Detection Area". Still static/hardcoded in the sense that `cctv` doesn't dynamically read *which* area a given camera actually uses — if an operator ever adds a second area via the app's own (IE-only) UI, `cctv apply`'s rule filter would still only match area 0. Low risk given the UI is barely usable at all on modern browsers.
- `root.Motion`'s windows/sensitivity (Story 3.1/3.3, still written by `cctv apply` on legacy-app cameras) describe a configuration surface that — now confirmed — is NOT what the migrated action rule actually triggers on (the app's own `vaconfig.cgi`-managed polygon is, and `cctv apply` now manages that too — see the 2026-08-04 write-support addition below). `cctv apply` still ALSO writes to `root.Motion` on these cameras every run; whether that's now pure dead weight (harmless but pointless) or whether it matters for some other purpose hasn't been investigated — worth a closer look if reconciler.py churn on this path ever gets revisited.
- `set_vmd_app_config` (2026-08-04, write support for the app's own detection area) only handles `Include`-type areas — no `Exclude`-area support, since none was observed on any of the 3 real units. If an operator manually adds an Exclude zone via the app's own (barely usable, IE-only) UI, the next `cctv apply` would silently drop it when `_ensure_vmd_app_area` rewrites `namedObjects` to a single full-frame Include area.
- `_ensure_vmd_app_area`'s "already full-frame" check (`_vmd_app_area_is_full_frame`) accepts ANY area covering the full frame, not specifically one named `_LEGACY_VMD_APP_AREA_NAME` ("Detection Area") — if a camera has a full-frame area under a different name (unlikely given every camera tested ships the same default name, but not impossible after manual UI edits) plus other non-full-frame areas, the function would treat it as "no change needed" while leaving the other areas untouched rather than consolidating to a single managed area.
- `192.168.1.72`'s `cctv apply` run always fails on the SMB step (`root.NetworkShare.N0.Address` rejected) — confirmed by the operator (2026-08-04) to be **expected**, not a bug: that camera is on a different network segment where the configured SMB share is genuinely unreachable. Consequence: `_ensure_vmd4_full_frame_area` (2026-08-04 addition) has never actually run through the real `cctv apply` code path on real hardware — only via an ad-hoc script calling `vapix.set_vmd4_configuration` directly, plus mocked unit tests of the reconciler wiring. If `.72`'s SMB config is ever addressed (or SMB reconciliation gets a per-camera skip/scope flag — see the pre-existing "no CLI flag to scope apply to a subset of cameras" deferred item from Story 3.6), worth a real end-to-end confirmation run.
- `get_vmd4_configuration`/`set_vmd4_configuration` (2026-08-04) work with an untyped raw `dict` rather than a dataclass model, by design (mirrors `get_vmd_app_config`/`set_vmd_app_config`'s "preserve what isn't understood" approach) — but this means a malformed/missing `"profiles"` or `"triggers"` key from an unexpected firmware response would surface as a `KeyError`/`AttributeError` inside `_ensure_vmd4_full_frame_area` rather than a clean `VapixError`. Only tested against the one real M3085-V's response shape.
- `status.py`'s `collect_status` reports action-rule `topic`/`target_template` as raw strings; `motion_source` (added this story) covers the app-vs-built-in distinction for the *installed app*, but doesn't cross-check that the actual rule's topic matches what `motion_source` implies it should be — a camera with a still-unmigrated stale rule (topic mismatch) would report `motion_source: "legacy app (.eap)"` while the actual rule topic underneath is the built-in one; `cctv status` doesn't currently surface that specific inconsistency (mitigated separately by `motion_rule_mismatch`, but the two fields aren't cross-validated against each other)
- No test covers a camera where `find_vmd_app` matches on `nice_name` only (neither known `Name`) reaching the action-rule step — pre-existing `_find_vmd_app` gap from Story 3.6, carried forward here since it also determines `use_legacy_app_topic`
- `get_vmd_app_config`'s `<namedObject>`/`<point>` regex parsing doesn't account for `Exclude`-type rules (only `Include` was observed on the 3 units tested) — an excluded sub-area would be parsed as just another polygon with no indication it should be subtracted, producing a misleading area-size description

## Deferred from: code review of 4-1-camera-status-collection-and-text-report (2026-07-24)

- Em dashes ("—") in `reporter.py` output (both the pre-existing `print_apply_results` FAILED line and the new `print_camera_status`) render as "�" on the operator's Windows console (cp1252 codepage) — cosmetic, pre-existing, orthogonal to this story; a `sys.stdout.reconfigure(encoding="utf-8")` or ASCII-safe separator would fix it project-wide if it becomes a real complaint
- `status.py` re-declares the same literal VAPIX group/param strings as `reconciler.py` (`_SMB_GROUP`, `_MOTION_GROUP`, etc.) rather than sharing them — deliberate per this story's Dev Notes, but if a third read-only consumer of these constants appears, promoting them to a small shared module becomes worth revisiting
- No test asserts the exact multi-line block formatting is stable/parseable beyond substring checks — acceptable for a human-readable report, but Story 4.2 (JSON output) is where a stable, tested schema actually matters
- `cctv status`'s exit-code contract (0/1/2, mirroring `apply` rather than `list`) is a design decision made in this story's Dev Notes rather than a pre-existing epics.md AC — confirm it still feels right once `--json` (Story 4.2) output consumers exist

## From spec-syslog-remote-forwarding (2026-10-06)

- Legacy syslog.conf: when `syslog.host` changes and the old forwarding line was hand-added without the `# cctv: remote syslog` marker (e.g. 192.168.1.60 today), the old `@oldhost` line is left in place and the camera forwards to both hosts. Fix would need to adopt/mark the identical hand line on first run, which costs a write + reboot.
- executor.py: any VapixError raised late in `reconcile()` (e.g. syslog step) discards the `settings_changed` already applied earlier in that run, so the FAILED line under-reports what was changed. Pre-existing behaviour, not syslog-specific.
- Legacy syslog.conf, rare hand-edit combos (review loop 2): (a) a marker-managed line to old host A plus an exact hand-added desired line for B -> early no-change return leaves A forwarding; (a') marker line rewritten to B while an unmarked B line at another severity survives -> B receives messages twice. Same root cause as the stale-line item above: unmarked forwarding lines are never reconciled.
