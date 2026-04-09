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
