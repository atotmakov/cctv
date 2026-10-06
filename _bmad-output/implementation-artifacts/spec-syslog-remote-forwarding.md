---
title: 'Remote syslog forwarding for all cameras'
type: 'feature'
created: '2026-10-06'
status: 'done'
baseline_commit: '6eed505'
context: []
---

<frozen-after-approval reason="human-owned intent — do not modify unless human renegotiates">

## Intent

**Problem:** Remote syslog to the Synology NAS was configured by hand on one camera (192.168.1.60); `cctv apply` cannot converge it, so other cameras and re-flashed ones drift.

**Approach:** Add an optional top-level `syslog:` block to `cameras.yaml` applied to every camera. Legacy fleet (AXIS OS 5.x, smb backend): manage one forwarding line in `/etc/syslog.conf` via `/admin-bin/editcgi.cgi`, then reboot the camera so sysklogd reloads it. M3085-V fleet (AXIS OS 12, sd_s3sync backend): use `/axis-cgi/remotesyslog.cgi` API 1.2 (live, no reboot).

## Boundaries & Constraints

**Always:** Read-before-write — touch nothing when current state already matches. Transport is fixed UDP, BSD/RFC3164 format. When a legacy camera is rebooted, the per-camera output must say so explicitly. Reboot is the LAST action of that camera's reconcile, after all other settings. Preserve every non-managed line of `syslog.conf` byte-for-byte.

**Ask First:** Any change to the legacy reboot policy (e.g. waiting for the camera to come back up). Writing the remotesyslog.cgi `configure` payload in a shape not confirmed by Axis docs.

**Never:** Run `cctv apply` against live cameras during this work (user will do it). Remove or disable syslog forwarding when `syslog:` is absent — omitted block means leave cameras untouched. Support TCP/TLS or per-profile syslog settings.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| Legacy, not configured | `syslog.conf` lacks managed line | Append marker comment + `*.<sev>;authpriv.none<TAB>@<host>`, reboot, report `syslog (camera rebooted)` | N/A |
| Legacy, already matches | managed line identical | No write, no reboot, no `syslog` entry | N/A |
| Legacy, host/severity changed | managed line differs | Replace only the managed line, reboot | N/A |
| Legacy, hand-added line (.60 today) | `*.info;authpriv.none ... @192.168.1.100` without marker | Treated as match if identical to desired line; no duplicate added | N/A |
| Legacy, port ≠ 514 | `syslog.port: 1514` | Camera FAILED before any write | VapixError: sysklogd 1.4.1 supports only port 514 |
| AXIS OS 12, differs | status `enabled:false` | `configure` enabled + single server; report `syslog` | VapixError on non-200 / error payload |
| AXIS OS 12, matches | enabled, one server equal to desired | No write | N/A |
| Block omitted | no `syslog:` key | No syslog reads or writes at all | N/A |
| Bad config | missing `host`, bad severity, port not int 1–65535 | `ConfigError` naming the key | ConfigError |

</frozen-after-approval>

## Code Map

- `src/cctv/config.py` -- add `SyslogConfig(host, port=514, severity="info")` and `CameraConfig.syslog: Optional[SyslogConfig]`; validation
- `src/cctv/vapix.py` -- new helpers: read/write file via editcgi, remotesyslog status/configure, restart camera
- `src/cctv/reconciler.py` -- `_reconcile_syslog` dispatched on `profile.storage.backend` (existing legacy-vs-OS12 convention); reboot after everything else
- `src/cctv/reporter.py` -- unchanged; reboot notice travels in `settings_changed`
- `tests/conftest.py`, `tests/test_config.py`, `tests/test_vapix.py`, `tests/test_reconciler.py` -- fixtures + tests
- `cameras.yaml.example`, `README.md` -- document the block

## Tasks & Acceptance

**Execution:**
- [x] `src/cctv/config.py` -- parse/validate `syslog` (host non-empty str; port int 1–65535, default 514; severity in debug/info/notice/warning/error/critical, default info) -- typed config
- [x] `src/cctv/vapix.py` -- `read_camera_file`/`write_camera_file` (editcgi GET parse `<textarea name=content>` with html-unescape; POST `save_file`, `mode=0100644`, `convert_crlf_to_lf=on`, `content`), `get_remote_syslog`/`set_remote_syslog` (remotesyslog.cgi 1.2 `status`/`setup`), `restart_camera` (`/axis-cgi/restart.cgi`); all raise VapixError like existing helpers -- VAPIX surface
- [x] `src/cctv/reconciler.py` -- `_reconcile_syslog`; legacy path returns a reboot-needed flag; `reconcile()` calls `restart_camera` last and appends `syslog (camera rebooted)` -- convergence
- [x] `tests/*` -- cover every I/O matrix row, plus "reboot happens after all other set calls" -- regression safety
- [x] `cameras.yaml.example`, `README.md` -- add commented `syslog:` example and Managed-settings row stating legacy cameras reboot on change -- docs

**Acceptance Criteria:**
- Given a legacy camera whose syslog.conf needs a change, when `cctv apply` runs, then output reads `applied (..., syslog (camera rebooted))` and exactly one restart call is made.
- Given a mixed run with a FAILED camera, when another camera needs syslog, then failure isolation is unchanged (only that camera reboots).

## Spec Change Log

- **Loop 1 → 2 (2026-10-06).** Trigger: acceptance auditor flagged the AXIS OS 12 write payload as unconfirmed; checking developer.axis.com/vapix/network-video/remote-syslog showed it was wrong (method `configure`, field `host`, `protocol: {"type": "UDP"}`, lowercase severity). Amended: Design Notes now pin the documented `setup` payload and severity spelling; VAPIX task names `setup`. Known-bad state avoided: every M3085-V rejecting the write, or being reconfigured on every run. KEEP: config parsing/validation, editcgi read/write helpers, `restart_camera`, legacy render logic (marker + adopt identical/same-host line), reboot-last ordering and `syslog (camera rebooted)` label, port-514 pre-check before any write, existing tests and docs. Fold in review patches: restart failure after write raises an explicit "reboot manually" VapixError; validate `syslog.host` as hostname/IP; line after marker is managed only if it is an `@` forwarding rule; verify editcgi "Wrote N bytes" against content length; non-dict JSON → VapixError; accept quoted `name="content"`; add tests for mixed-run isolation, `reconcile()` on an sd_s3sync camera, and remotesyslog.cgi non-200.

## Design Notes

Managed line on legacy cameras (severity `error`→`err`, `critical`→`crit` in selector syntax):
```
# cctv: remote syslog
*.info;authpriv.none					@192.168.1.100
```
Match by the line ending in `@<host>` (marker optional) so the hand-configured .60 is recognised. AXIS OS 12: per developer.axis.com remote-syslog docs, `setup` both configures and enables; server entry is `{"address", "port", "protocol": "UDP", "syslogFormat": "RFC3164", "severity"}` with severity spelled `Debug|Informational|Notice|Warning|Error|Critical` (map from config's lowercase names). `status` returns `{"enabled", "servers": [same shape]}`; compare managed fields only, severity case-insensitively. Live write is unverified on hardware — note this in a code comment like other unverified helpers.

## Verification

**Commands:**
- `.venv/Scripts/python -m pytest -q` -- expected: all tests pass

## Suggested Review Order

**Entry point: where syslog joins the per-camera flow**

- Syslog runs last; legacy path reboots only after a real write, restart failure is explicit.
  [`reconciler.py:153`](../../src/cctv/reconciler.py#L153)

- Legacy port check runs before any read or write, so a bad port touches nothing.
  [`reconciler.py:130`](../../src/cctv/reconciler.py#L130)

**Legacy 5.x: managing one line in syslog.conf**

- Core idempotent render: no-op if present, marker-managed replace, adopt same-host line, else append.
  [`reconciler.py:523`](../../src/cctv/reconciler.py#L523)

- Only real `@host` rules count as managed, so unrelated lines are never clobbered.
  [`reconciler.py:515`](../../src/cctv/reconciler.py#L515)

- Interrupted write surfaces "reboot manually" because a re-run would see no change.
  [`reconciler.py:553`](../../src/cctv/reconciler.py#L553)

- sysklogd selector syntax; error/critical map to err/crit.
  [`reconciler.py:510`](../../src/cctv/reconciler.py#L510)

**AXIS OS 12: remotesyslog.cgi**

- Documented `setup` server entry; explicit type All avoids audit-only forwarding.
  [`reconciler.py:572`](../../src/cctv/reconciler.py#L572)

- Loose readback compare keeps unverified `status` shape from reconfiguring every run.
  [`reconciler.py:584`](../../src/cctv/reconciler.py#L584)

- Single-server full replace via `setup`, guarded against non-list `servers`.
  [`reconciler.py:600`](../../src/cctv/reconciler.py#L600)

**VAPIX surface**

- editcgi write verifies "Wrote N bytes" against content length before any reboot.
  [`vapix.py:328`](../../src/cctv/vapix.py#L328)

- editcgi read: textarea extraction, quoted or unquoted name, HTML-unescaped.
  [`vapix.py:308`](../../src/cctv/vapix.py#L308)

- JSON-RPC wrapper: non-200, non-dict, and error payloads all become VapixError.
  [`vapix.py:368`](../../src/cctv/vapix.py#L368)

- Reboot trigger; returns immediately, never waits for the camera.
  [`vapix.py:279`](../../src/cctv/vapix.py#L279)

**Config**

- Host restricted to hostname/IPv4 because it is written verbatim into syslog.conf.
  [`config.py:142`](../../src/cctv/config.py#L142)

- Typed defaults: port 514, severity info.
  [`config.py:45`](../../src/cctv/config.py#L45)

**Peripherals**

- Reconciler tests, using a real M3005 syslog.conf excerpt as fixture.
  [`test_reconciler.py:1839`](../../tests/test_reconciler.py#L1839)

- AC2 failure-isolation test across two cameras.
  [`test_reconciler.py:2096`](../../tests/test_reconciler.py#L2096)

- VAPIX helper tests (editcgi, restart, remotesyslog.cgi).
  [`test_vapix.py:952`](../../tests/test_vapix.py#L952)

- Config parsing and validation tests.
  [`test_config.py:336`](../../tests/test_config.py#L336)

- User docs: reboot warning and port-514 limit.
  [`README.md:82`](../../README.md#L82)
  [`cameras.yaml.example:20`](../../cameras.yaml.example#L20)
