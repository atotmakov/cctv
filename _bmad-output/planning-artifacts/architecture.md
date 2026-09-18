---
stepsCompleted: [1, 2, 3, 4, 5, 6, 7, 8]
status: 'complete'
completedAt: '2026-04-01'
inputDocuments: ['_bmad-output/planning-artifacts/prd.md']
workflowType: 'architecture'
project_name: 'cctv'
user_name: 'atotmakov'
date: '2026-03-31'
---

# Architecture Decision Document

_This document builds collaboratively through step-by-step discovery. Sections are appended as we work through each architectural decision together._

## Project Context Analysis

### Requirements Overview

**Functional Requirements: 27 FRs across 6 capability areas**

| Area | FRs | Architectural Implication |
|---|---|---|
| Camera Discovery | FR1–FR5 | Concurrent subnet scanner + Axis device identifier |
| Configuration Management | FR6–FR11 | YAML loader + schema validator |
| State Convergence | FR12–FR16 | Read-before-write reconciler + apply executor |
| SMB Share Configuration | FR17–FR18 | VAPIX API client (GET + SET for SMB) |
| Motion Detection Configuration | FR19–FR20 | VAPIX API client (GET + SET for motion) |
| Observability & Reporting | FR21–FR27 | Structured result collector + formatter + exit code manager |

**Non-Functional Requirements — architectural drivers:**

- **Performance:** Subnet scan must be parallelised (NFR). Discovery must complete in <30s on a /24. This forces async or threaded network I/O.
- **Security:** Credentials must never appear in stdout/stderr. HTTP Digest Auth for all VAPIX calls. No credential persistence.
- **Reliability:** Failure isolation per camera — continue-on-error is mandatory. Configurable per-camera timeout (default 5s).

**Scale & Complexity:**

- Complexity: **Low** — no database, no persistence layer, no web server, no concurrent users. Pure network I/O.
- Primary domain: CLI / network client
- Estimated architectural components: **8**

### Technical Constraints & Dependencies

- Python — `requests` (VAPIX HTTP), `pyyaml` (config), `ipaddress` (CIDR handling)
- VAPIX API: HTTP Digest Auth; specific endpoints for SMB config and motion detection GET/SET are the key implementation unknowns
- Read-before-write mandatory: must GET current camera state before SET to implement idempotency (FR13–FR14)
- Two distinct operation modes: `list` (read-only, no side effects) vs `apply` (read-write, convergence)

### Cross-Cutting Concerns Identified

1. **Error handling** — spans scanner, VAPIX client, reconciler, and executor; must be consistent and failure-isolating per camera
2. **Credential hygiene** — config credentials must never reach stdout/stderr; enforced across all layers
3. **Timeout management** — configurable timeout applied uniformly to all network operations
4. **stdout/stderr discipline** — status output to stdout, errors/diagnostics to stderr; enforced at the output layer

## Starter Template Evaluation

### Primary Technology Domain

Python CLI tool. No JS-style scaffold generator applies — the "starter" for a Python CLI is the project structure and tooling decisions established in `pyproject.toml`.

### Selected Approach: Typer + src layout + pytest

**Rationale:**
- **Typer** over Click: fewer decorators, type hints drive argument parsing, cleaner command definitions — fits the tool's focused scope well
- **src layout** over flat: prevents accidental imports from the project root during development; pytest standard
- **Plain `print()`** over Rich: the output format is simple tabular text; no formatting library needed
- **`pyproject.toml`** only: no `setup.py`, no `setup.cfg` — modern standard

### Initialization Command

```bash
mkdir cctv && cd cctv
python -m venv .venv && source .venv/bin/activate   # or .venv\Scripts\activate on Windows
pip install typer requests pyyaml pytest
```

No scaffold generator — the project is initialized by creating the structure below.

### Project Structure

```
cctv/
├── pyproject.toml
├── README.md
├── src/
│   └── cctv/
│       ├── __init__.py
│       ├── cli.py          # Typer app, command entry points
│       ├── config.py       # YAML loader + validator
│       ├── scanner.py      # Subnet scanner (concurrent)
│       ├── vapix.py        # VAPIX API client (Digest Auth, GET/SET)
│       ├── reconciler.py   # Desired-vs-actual state comparison
│       ├── executor.py     # Apply executor (failure-isolated)
│       └── reporter.py     # Output formatter (stdout/stderr, exit codes)
└── tests/
    ├── __init__.py
    ├── test_config.py
    ├── test_scanner.py
    ├── test_vapix.py
    ├── test_reconciler.py
    └── test_executor.py
```

### Architectural Decisions Established

**Language & Runtime:** Python 3.11+ (type hints required by Typer)

**CLI Framework:** Typer 0.24.1 — commands declared as typed functions

**Dependencies:**
- `typer==0.24.1`
- `requests==2.33.1`
- `pyyaml==6.0.3`

**Dev/Test Dependencies:**
- `pytest==9.0.2`

**Entry point:**
```toml
[project.scripts]
cctv = "cctv.cli:app"
```

**Testing:** pytest with `pip install -e .` before test runs

**Note:** Project initialization and `pyproject.toml` setup should be the first implementation story.

## Core Architectural Decisions

### Decision Priority Analysis

**Critical Decisions (Block Implementation):**
- VAPIX 3 CGI as API protocol, targeting firmware 5.51.7.4
- `CameraResult` dataclass as the cross-cutting result type
- `ThreadPoolExecutor` for concurrent subnet scanning

**Important Decisions (Shape Architecture):**
- Distribution via `pip install git+...` (PyPI post-MVP)
- No persistent state — fully stateless per run

**Deferred Decisions (Post-MVP):**
- PyPI package release
- asyncio migration if fleet size grows beyond ~50 cameras

### Concurrency Model

**Decision:** `concurrent.futures.ThreadPoolExecutor` (stdlib)

**Rationale:** Subnet scanning and VAPIX calls are I/O-bound HTTP probes. ThreadPoolExecutor handles this well for a fleet of 2–10 cameras with no additional dependencies. asyncio deferred to post-MVP if scale demands it.

**Implementation note:** Scanner spawns one thread per IP in the CIDR range, bounded by a configurable `max_workers` (default: 50). Each thread attempts an HTTP probe with the configured timeout.

### VAPIX API Protocol

**Decision:** VAPIX CGI — parameter API via `/axis-cgi/param.cgi`, plus three
further API families that `param.cgi` does not cover (see below).

**Target firmware:** two generations, one per profile — Axis 5.51.7.4 (legacy
SMB fleet) and Axis 12.11.72 (M3085-V SD+S3 fleet).

**Authentication:** HTTP Digest Auth on every request (handled by
`requests.auth.HTTPDigestAuth`).

**Camera identification during discovery:** HTTP probe to
`/axis-cgi/param.cgi?action=list&group=root.Brand` — Axis cameras return brand
information; non-Axis hosts return 401 or a connection error.

**Protocol pattern:**
```
GET  /axis-cgi/param.cgi?action=list&group=<ParamGroup>
POST /axis-cgi/param.cgi?action=update&<Param>=<Value>
```

#### Rule zero: discover, don't assume

API shape varies by model *and* firmware, and the two generations in this fleet
differ materially. Verify against the specific unit before writing code for it:

```
POST /axis-cgi/apidiscovery.cgi   {"apiVersion":"1.0","method":"getApiList"}
GET  /axis-cgi/param.cgi?action=list&group=root.Brand,root.Properties.Firmware
GET  /axis-cgi/applications/list.cgi
```

Two habits that repeatedly proved faster than guessing:

- **Read the camera's own web UI network traffic.** Several settings live on
  endpoints that `apidiscovery.cgi` does not usefully name. Toggling the setting
  in the UI and reading the resulting request is definitive; guessing method
  names is not. Both the NTP fallback and DLPU endpoints below were found this
  way after JSON-RPC-style guesses all returned "method does not exist".
- **Read a parameter back after writing it.** `param.cgi` accepts and stores
  malformed values without complaint, so a write returning 200 is not evidence
  the intended value landed.

#### Verified parameter groups (`param.cgi`)

| Group / parameter | Generation | Notes |
|---|---|---|
| `root.NetworkShare.N0.{Address,Share,Username,Password}` | 5.x only | **Errors with `Error -1` on 12.x**, despite `root.Properties.NetworkShare` existing there. SMB is a genuine dead end on the newer generation — not a bug to debug. |
| `root.Motion.M<n>.{Left,Right,Top,Bottom,Sensitivity,Name}` | 5.x only | Full frame is `0/9999/0/9999`. Empty or erroring on 12.x — VMD4 does not use it. |
| `root.Storage.S0.CleanupMaxAge` | both | SD card (`SD_DISK`). |
| `root.Storage.S1.CleanupMaxAge` | both | Network share. Same semantics as S0; `0` = unlimited, leaving the card as a rolling buffer managed by its own fill-based cleanup policy rather than by age. |
| `root.Time.POSIXTimeZone` | both | |
| `root.Time.NTP.Server`, `root.Time.ObtainFromDHCP` | both | **Reads/writes only the first entry** of the same list the modern REST endpoint exposes. Insufficient on its own — see NTP below. |
| `root.Network.HostName`, `root.Network.VolatileHostName.HostName` | both | Static vs DHCP-assigned. Determines storage namespacing (FR50). |
| `root.Properties.Firmware.Version` | both | Read-only precondition (FR39/FR40). |
| `root.Sds3sync.*` | 12.x | Sync ACAP config: `S3Endpoint`, `S3Region`, `S3Bucket`, `S3AccessKey`, `S3SecretKey`, `S3PathStyle`, `S3InsecureTLS`, `RecordingPath`, `IntervalSeconds`, `HeartbeatIntervalSeconds`, `Prefix`. `Prefix` is deliberately unmanaged (FR51). |

**Identical config does not imply identical behaviour.** Two cameras reported
byte-identical `root.Time` values while one had a correct clock and the other
was frozen years in the past, because DHCP was silently handing out no NTP
source on that network. Where a setting has an observable effect, verify the
effect (for the clock: the HTTP `Date:` response header), not just the
parameter.

#### Motion detection: two incompatible APIs

The generations do not share a motion model, and this is the single largest
source of divergence between profiles.

**Legacy (`root.Motion`, AXIS OS 5.x)** — window-based, with one 0–100
`Sensitivity` scalar per window.

**VMD4 (`/local/vmd/control.cgi`, AXIS OS 12.x)** — a JSON control API on the
built-in `vmd` application. Detection rule: if `param.cgi` `Motion` comes back
empty *and* `applications/list.cgi` shows `vmd` Running, the camera is VMD4.

```
POST /local/vmd/control.cgi   {"apiVersion":"1.4","method":"getConfiguration"}
POST /local/vmd/control.cgi   {"apiVersion":"1.4","method":"setConfiguration","params":{...}}
```

- **There is no sensitivity scalar.** Tuning is filter-based:
  `sizePercentage` (minimum object size as % of frame; lower is more sensitive,
  documented floor `3`), `timeShortLivedLimit`, `distanceSwayingObject`.
- **The write payload key is `params`, not `data`** — unlike the
  `/config/rest/` family below, which uses `data`. Easy to conflate.
- **Read-modify-write the fetched payload**; never push a constructed one.
  `configurationStatus`, profile `uid`/`name`, and unrelated trigger types must
  survive the round trip.
- The factory-default profile's `includeArea` trigger does **not** cover the
  full frame (~97% on 12.x, ~60% on the legacy app's own area). Motion outside
  it never fires (FR49). Full frame is the corner set
  `[[-1,-1],[-1,1],[1,1],[1,-1]]`.
- The app can ship `Stopped` on factory units and after major-version firmware
  upgrades; it must be started before it will do anything.

#### Events and actions: Action1 SOAP only

**As of AXIS OS 12 there is still no modern REST API for events, actions, or
recipients** — `apidiscovery.cgi` will not list one. The legacy Action1 SOAP
service at `/vapix/services` remains the only way to configure action rules on
the newest firmware. Do not go looking for a REST replacement.

Every action is a **two-step** creation: `AddActionConfiguration` (what to do,
returns a `ConfigurationID`) then `AddActionRule` (when to do it, referencing
that ID as `PrimaryAction`).

Three gotchas, all confirmed against real hardware:

- **No in-place edit.** `SetActionConfigurationParameters` returns
  `Optional action not implemented`. Changing any parameter means
  `RemoveActionRule` + `RemoveActionConfiguration`, then recreating both — which
  is exactly why FR48 is written as remove-and-recreate rather than update.
- **The "any profile" topic wildcard is read-only.**
  `tnsaxis:CameraApplicationPlatform/VMD/Camera1ProfileANY` round-trips fine on
  `GetActionRules` for pre-existing rules, but `AddActionRule` **rejects** it
  with `failed to parse topic expression`. Note the fault message mangles the
  `tnsaxis:` prefix to `axis:` — a red herring, not the actual problem. Create
  rules against the concrete topic (`.../Camera1Profile<uid>`) instead (FR47).
- **Namespaces must all be declared on `soap:Envelope`:** `soap`, `aa`,
  `wsnt="http://docs.oasis-open.org/wsn/b-2"`,
  `tns1="http://www.onvif.org/ver10/topics"`,
  `tnsaxis="http://www.axis.com/2009/event/topics"`.

Event topics and message filters in use:

| Motion source | Topic | Message content filter |
|---|---|---|
| Built-in window motion | `tns1:VideoAnalytics/tnsaxis:MotionDetection` | `//SimpleItem[@Name="motion" and @Value="1"]`, plus a `window` clause when a full-frame window id is known |
| Legacy VMD app | `tns1:RuleEngine/tnsaxis:VideoMotionDetection/motion` | `active=1` and `areaid=0` |
| VMD4 | `tnsaxis:CameraApplicationPlatform/VMD/Camera1Profile<uid>` | `active=1` |

Recording actions use template token
`com.axis.action.unlimited.recording.storage` with `storage_id` of
`NetworkShare` or `SD_DISK`, plus `pre_duration`/`post_duration` in
milliseconds.

#### Modern REST config API (`/config/rest/...`)

A third family, distinct from both `param.cgi` and the `*.cgi` JSON-RPC
endpoints. Writes mirror the `data` envelope that the GET returns — posting
bare fields fails with `There is no 'data' field in the request body`.

**NTP fallback servers** — the camera's real multi-entry fallback list, of which
the legacy `root.Time.NTP.Server` param is only the first element:

```
GET  /config/rest/network-time-sync/v1/ntp/client
POST /config/rest/network-time-sync/v1/ntp/client   {"data":{"staticServers":[...]}}
```

`staticServers` is a **full replace, not an append** — post the complete
intended list or existing entries are dropped. `apidiscovery.cgi`'s `"id":"ntp"`
entry is *not* this API and is a red herring for it.

**DLPU / object-detection engine** — the Deep Learning Processing Unit backing
AXIS Object Analytics. Not managed by cctv, documented because it is invisible
to a `param.cgi` audit:

```
GET   /config/rest/video-analytics/v1/dlpu/enabled
PATCH /config/rest/video-analytics/v1/dlpu/enabled   {"data":false}
```

#### ACAP application lifecycle

```
POST /axis-cgi/applications/upload.cgi              (multipart field name: packfil)
GET  /axis-cgi/applications/control.cgi?action=start|stop&package=<name>
GET  /axis-cgi/applications/list.cgi
GET  /axis-cgi/admin/systemlog.cgi?appname=<name>
```

- **Package name is not known until after install** and varies by package
  version — the legacy VMD `.eap` installs as `VideoMotionDetection`, not `vmd`.
  Re-list after uploading and use whatever name appears.
- **`Status="Idle"` is not `Stopped`.** The legacy VMD 2.2.1 app settles into
  `Idle` once running. Treating anything-but-`Running` as stopped re-issues a
  start call on every reconcile; only `Stopped` should trigger a start.
- **The sync ACAP reads its config only at startup.** Started before its
  `root.Sds3sync.*` params exist, it logs `not configured yet` and sits idle
  indefinitely even after the params are later written. Hence FR42's ordering
  rule: configure first, then start; restart if config changed while running.
- **Re-uploading the same package name upgrades in place.** Confirmed the app
  stayed `Running` throughout, with its stored config and its uploaded-file
  dedup state intact.
- **Unsigned packages are not rejected** when `AllowUnsigned` is `true`
  (`applications/config.cgi?action=get&name=AllowUnsigned`), which is the
  default observed across this fleet — a signed build ran alongside an unsigned
  one of the same app for months. Prefer signed packages anyway, since that
  clears the camera's own "ACAP apps: Unsigned" security warning, but do not
  treat signing as a hard technical requirement; it is not one.

#### What `param.cgi` does *not* cover

A full `param.cgi?action=list` dump is the natural way to diff a new camera
against a known-good reference, and it is genuinely useful — but it is not the
whole configuration surface, and treating it as complete hides real
differences. At least three categories live entirely outside it:

- **Installed-app metadata** — version, `Status`, and `SignatureStatus` come
  from `applications/list.cgi`. A signed-vs-unsigned build difference between
  two cameras is invisible to a `param.cgi` diff.
- **`/config/rest/...` settings** — e.g. the DLPU toggle above.
- **Web-UI display preferences** — a generic per-key store, no `get`
  counterpart (404), verifiable only in the browser:
  `/axis-cgi/clientnotes/set.cgi?group=<g>&key=<k>&value=<v>`.

When auditing fleet drift, diff **both** `param.cgi?action=list` and
`applications/list.cgi`. Expect identity-only noise in the former (hostname,
MAC, IP, serial, RTP multicast addresses, per-camera storage prefixes) and
ignore it.

### Error Handling & Result Model

**Decision:** `CameraResult` dataclass as the universal result type flowing from executor → reporter

```python
from dataclasses import dataclass
from enum import Enum
from typing import Optional

class CameraStatus(Enum):
    APPLIED = "applied"
    NO_CHANGE = "no_change"
    FAILED = "failed"

@dataclass
class CameraResult:
    ip: str
    model: Optional[str]
    status: CameraStatus
    settings_changed: list[str]   # e.g. ["smb_ip", "motion"]
    error: Optional[str]          # populated only on FAILED
```

**Rationale:** Structured result type makes the reporter and tests significantly cleaner. All executor logic produces `CameraResult`; reporter consumes it. No string parsing of outcomes.

**Failure isolation:** Each camera is processed in a `try/except` block inside the executor. Any exception (connection timeout, VAPIX error, auth failure) produces a `CameraResult(status=FAILED, error=<message>)`. The loop continues regardless.

### Distribution

**Decision:** `pip install git+https://github.com/atotmakov/cctv.git` for MVP

**Rationale:** Zero overhead for a personal tool. PyPI release deferred to post-MVP if broader adoption warrants it.

**`pyproject.toml` install mode during development:** `pip install -e .`

### Rejected Alternatives

Approaches investigated against real hardware and deliberately not adopted.
Recorded because the investigation cost was real and the findings would
otherwise be re-derived from scratch.

#### Direct SFTP clip upload from the camera

**Rejected in favour of** SD-card recording plus the `sd_to_s3_sync` ACAP.

Axis cameras can upload video clips over SFTP natively, via the
`com.axis.action.unlimited.send_videoclip.sftp` action template — no third-party
app required. This was implemented end-to-end against a Synology NAS before
being abandoned. It works, but couples every camera directly to one always-on
NAS, offers no retry or dedup when that NAS is unreachable, and puts the
credentials for a writable NAS account on every camera. SD-buffer-then-sync
degrades better: the camera keeps recording while the destination is down, and
the ACAP owns retry and dedup.

If it is ever revisited, these cost the most to find:

- **`ssh_auth_type` is the parameter that matters.** `1` = public key, which
  Axis's own docs mark *"currently not supported"*; `2` = password. Leaving it
  at `1` while setting a `password` makes the camera attempt unsupported pubkey
  auth, fail, and report a generic misleading error (`Login denied` on older
  firmware, `Failed to transfer data` on newer) **without ever sending a
  password login attempt.** It is indistinguishable from a network, credential,
  or firmware fault from the camera's logs alone. Check this first.
  - Diagnosed by packet capture (full TCP+SSH handshake and key exchange, then
    a clean FIN before any userauth) confirmed against `sshd` at `LogLevel
    DEBUG3` — a deliberately wrong password from another client always produced
    an authentication-failure line, the camera's connections produced none.
  - A two-major-version firmware upgrade did **not** fix it; the bug was a
    config value, not the bundled libssh2.
- **`create_folder` is not a boolean.** Whatever string it holds becomes a
  literal extra subfolder name under `upload_path` — `"yes"` creates a folder
  named `yes`. Use `""` to write directly into `upload_path`.
- **Synology-specific:** a share's Windows ACL can allow "create files" while
  denying "create folders", breaking auto-provisioning while plain writes
  succeed; and setting a DSM home directory for the SFTP account mid-setup
  silently re-roots its chroot, invalidating any absolute `upload_path`
  configured earlier.

#### Automated firmware upgrades

**Rejected permanently** — see FR40. The upgrade API works
(`/axis-cgi/firmwaremanagement.cgi`, multipart `data` JSON part plus `fwimage`),
but a real upgrade failure observed on two units showed why it does not belong
in an unattended convergence loop: a direct jump across two major versions was
accepted with `200 OK`, rebooted, failed initialisation, and auto-rolled back
within about a minute:

```
fwmgr-init: Rebooting to rollback firmware upgrade. Reason: Firmware initialization failed.
rrdetect: Firmware rollback detected after 0 min.
```

Axis's dual-bank safety net meant no lasting damage — but the target firmware
never applied, and the camera reported success. Crossing major versions needs
an intermediate hop, verification between hops, and a human watching. cctv
therefore treats firmware as a **precondition it checks and refuses to act on**,
never a target it converges (FR39/FR40).

Operator notes for doing it by hand: upgrade one major version at a time; after
each hop poll `root.Properties.Firmware.Version` until it reports the target,
then check `root.Brand` for basic health and grep the system log for
`rollback|initialization failed` to catch a silent rollback. A hop that never
drops reachability is itself a warning sign — a real upgrade reboots the camera.

### Deliberately Unmanaged Settings

Settings this fleet cares about that cctv does **not** converge. Listed so an
audit diff against a reference camera does not read them as regressions, and so
the boundary stays explicit rather than accidental.

| Setting | Why unmanaged |
|---|---|
| `root.ImageSource.I0.CaptureFrequency` | Mains flicker frequency — a property of the installation site (50/60 Hz), not of the fleet. |
| `root.Tampering.T0.DarkDetectionEnabled` | Site/scene judgement. |
| `root.ImageSource.I0.CameraTiltOrientation` | **Tied to physical mounting.** Copying a reference camera's value is only correct if the new unit is mounted identically; a wrong value rotates the recorded image. Always check the live image before setting it — never infer it from a config diff. |
| DLPU / object-detection engine | Only matters when `objectanalytics` is running, which it is not anywhere in this fleet. |
| Web-UI 24-hour clock preference | Pure display preference, per-browser-key store, no read-back API. |
| `objectanalytics` application | Not part of the recording pipeline on any camera. Left alone deliberately. |

Diagnostic access — SSH shell (`root.Network.SSH.Enabled`, normally `no`),
elevated log levels — is likewise unmanaged and must be reverted by hand after
any invasive debugging session.

### Decision Impact Analysis

**Implementation Sequence:**
1. `pyproject.toml` + project scaffold
2. `config.py` — YAML loader + validator (no network dependency, testable first)
3. `vapix.py` — VAPIX 3 client (requires hardware verification of param names)
4. `scanner.py` — ThreadPoolExecutor subnet probe using `vapix.py` for identification
5. `reconciler.py` — desired-vs-actual comparison, produces change plan
6. `executor.py` — applies changes, collects `CameraResult` list
7. `reporter.py` — formats output, manages exit codes
8. `cli.py` — Typer commands wiring all above together

**Cross-Component Dependencies:**
- `vapix.py` is a dependency of both `scanner.py` and `executor.py`
- `CameraResult` dataclass is shared between `executor.py` and `reporter.py`
- `config.py` output feeds `scanner.py` (subnet) and `executor.py` (desired state)
- `reconciler.py` sits between `vapix.py` (current state) and `executor.py` (apply decisions)

## Implementation Patterns & Consistency Rules

### Critical Conflict Points Identified

5 areas where inconsistent choices would cause problems:
1. Which module makes `requests` calls (network boundary)
2. How errors propagate between modules
3. Where `print()` calls live (output boundary)
4. How VAPIX GET vs SET calls are structured
5. What goes in `__init__.py` vs module files

### Naming Patterns

**Python conventions (enforced by language):**
- Functions and variables: `snake_case`
- Classes and dataclasses: `PascalCase`
- Constants: `SCREAMING_SNAKE_CASE`
- Modules: single short `snake_case` word (`vapix`, `scanner`, `config`)

**Config YAML keys:** `snake_case` — matches Python variable names directly after `yaml.safe_load()`

**Examples:**
```python
# Correct
def get_camera_params(ip: str) -> dict: ...
class CameraResult: ...
DEFAULT_TIMEOUT = 5

# Wrong
def GetCameraParams(ip): ...
class camera_result: ...
```

### Structure Patterns

**Module responsibility boundaries — strictly enforced:**

| Module | Owns | Does NOT own |
|---|---|---|
| `vapix.py` | All `requests` calls | Business logic, output |
| `reporter.py` | All `print()` calls, `sys.exit()` | Network, config parsing |
| `config.py` | YAML parsing, schema validation | Network, output |
| `scanner.py` | Subnet iteration, concurrency | VAPIX protocol details |
| `reconciler.py` | Desired-vs-actual comparison | Network calls, output |
| `executor.py` | Orchestration, failure isolation | Protocol details, output |
| `cli.py` | Typer command wiring | Business logic |

**Rule:** No `import requests` outside `vapix.py`. No `print()` outside `reporter.py`.

**`__init__.py` files:** Empty — no re-exports, no package-level imports.

**Test location:** `tests/` directory, mirroring module names. `test_vapix.py` tests `vapix.py`, etc.

### Format Patterns

**VAPIX client interface — consistent function signatures:**

```python
# GET pattern
def get_params(ip: str, group: str, auth: HTTPDigestAuth, timeout: int) -> dict[str, str]:
    """Returns {param_name: value} or raises VapixError."""

# SET pattern
def set_params(ip: str, params: dict[str, str], auth: HTTPDigestAuth, timeout: int) -> None:
    """Raises VapixError on failure."""
```

**Config dataclass — output of `config.py`:**

```python
@dataclass
class CameraConfig:
    subnet: str
    username: str
    password: str
    smb_ip: str
    smb_share: str
    smb_username: str
    smb_password: str
    motion_enabled: bool
    motion_sensitivity: int
    timeout: int = 5
```

### Error Handling Patterns

**Exception hierarchy** — defined in `vapix.py`, imported where needed:

```python
class VapixError(Exception):
    """VAPIX API call failed (non-2xx, auth failure, timeout)."""

class ConfigError(Exception):
    """Config file missing, unreadable, or schema invalid."""
```

**Propagation rule:**
- `vapix.py` raises `VapixError` — never returns None on failure
- `config.py` raises `ConfigError` — never returns None on failure
- `executor.py` catches all exceptions per camera, converts to `CameraResult(status=FAILED, error=str(e))`
- `cli.py` catches `ConfigError` at startup, prints to stderr, exits with code 2

**Credentials in error messages:** Never include raw credential values in exception messages or `error` field of `CameraResult`.

### Process Patterns

**Idempotency implementation — read-before-write is mandatory:**

```python
# In reconciler.py — ALWAYS do this
current = vapix.get_params(ip, group, auth, timeout)
if current[param] != desired_value:
    vapix.set_params(ip, {param: desired_value}, auth, timeout)
    changed.append(param)
# Never call set_params without checking current state first
```

**Timeout:** Always pass `timeout` from `CameraConfig` — never hardcode a timeout value in any module.

**stdout/stderr discipline:**
- `reporter.py` writes camera status lines and summary to `sys.stdout`
- `reporter.py` writes error details and fatal messages to `sys.stderr`
- No other module writes to either

### Enforcement Guidelines

**All agents MUST:**
- Import `requests` only in `vapix.py`
- Call `print()` / `sys.stdout.write()` only in `reporter.py`
- Pass `timeout` from config — never hardcode
- Catch exceptions per camera in `executor.py`, not in `vapix.py`
- Use `CameraResult` as the return type from `executor.py` — never raw strings

**Anti-patterns to avoid:**
```python
# Wrong: requests outside vapix.py
import requests  # in scanner.py — FORBIDDEN

# Wrong: print outside reporter.py
print(f"Applying to {ip}")  # in executor.py — FORBIDDEN

# Wrong: hardcoded timeout
requests.get(url, timeout=5)  # use config.timeout

# Wrong: credentials in error
raise VapixError(f"Auth failed for {username}:{password}")  # FORBIDDEN
```

## Project Structure & Boundaries

### Complete Project Directory Structure

```
cctv/
├── pyproject.toml              # Package metadata, dependencies, entry point
├── README.md                   # Install, usage, config schema, plaintext creds warning
├── cameras.yaml.example        # Reference config file with all keys documented
├── .gitignore                  # Excludes cameras.yaml, .venv, __pycache__, dist/
├── .github/
│   └── workflows/
│       └── test.yml            # Run pytest on push (optional, post-MVP)
├── src/
│   └── cctv/
│       ├── __init__.py         # Empty
│       ├── cli.py              # Typer app; `list` and `apply` command definitions
│       ├── config.py           # YAML loader, schema validator, CameraConfig dataclass
│       ├── scanner.py          # ThreadPoolExecutor subnet scan; returns list of Axis IPs
│       ├── vapix.py            # VAPIX 3 client; VapixError; get_params/set_params
│       ├── reconciler.py       # Compares CameraConfig desired state vs VAPIX current state
│       ├── executor.py         # Per-camera apply loop; produces list[CameraResult]
│       └── reporter.py         # Formats stdout output, stderr errors, sys.exit()
└── tests/
    ├── __init__.py
    ├── conftest.py             # Shared pytest fixtures (mock auth, sample config, etc.)
    ├── test_config.py          # Config loading, validation, error cases
    ├── test_scanner.py         # Subnet iteration, Axis identification, timeout handling
    ├── test_vapix.py           # get_params/set_params, VapixError cases, auth
    ├── test_reconciler.py      # Desired-vs-actual comparison, change plan generation
    ├── test_executor.py        # Failure isolation, CameraResult production
    ├── test_reporter.py        # Output format, stdout/stderr routing, exit codes
    └── test_cli.py             # CLI command wiring integration tests
```

### Requirements to Structure Mapping

| FR Category | FRs | Primary File(s) |
|---|---|---|
| Camera Discovery | FR1–FR5 | `scanner.py`, `vapix.py` |
| Configuration Management | FR6–FR11 | `config.py` |
| State Convergence | FR12–FR16 | `reconciler.py`, `executor.py` |
| SMB Share Configuration | FR17–FR18 | `vapix.py` |
| Motion Detection Configuration | FR19–FR20 | `vapix.py` |
| Observability & Reporting | FR21–FR27 | `reporter.py`, `cli.py` |

### Architectural Boundaries

**External boundary:** `vapix.py` is the sole point of contact with the outside world (network). All `requests` calls are here. Everything else is pure Python logic testable without network.

**Module call graph:**
```
cli.py
  ├── config.py          (load + validate config)
  ├── scanner.py         (discover camera IPs)
  │     └── vapix.py     (HTTP probe per IP)
  └── executor.py        (apply loop)
        ├── reconciler.py
        │     └── vapix.py  (GET current state)
        ├── vapix.py         (SET desired state)
        └── reporter.py      (stream per-camera results)
```

**Data flow through the system:**

```
cameras.yaml
    ↓ config.py
CameraConfig (dataclass)
    ↓ scanner.py + vapix.py
list[str]  (discovered Axis IPs)
    ↓ executor.py + reconciler.py + vapix.py
list[CameraResult]  (per-camera outcomes)
    ↓ reporter.py
stdout (status lines + summary) + stderr (errors) + exit code
```

### Integration Points

**External integrations:**
- Axis cameras over HTTP — `vapix.py` only, VAPIX 3 CGI `/axis-cgi/param.cgi`, HTTP Digest Auth

**Internal communication:**
- All inter-module data passed as return values (no globals, no shared mutable state)
- `CameraConfig` flows from `config.py` → `cli.py` → `scanner.py` / `executor.py`
- `CameraResult` flows from `executor.py` → `reporter.py`

### File Organization Patterns

**`cameras.yaml.example`** — committed to git as the reference config. Actual `cameras.yaml` is gitignored (contains plaintext credentials).

**`conftest.py`** — shared fixtures: a sample `CameraConfig`, a mock `HTTPDigestAuth`, mock `requests.get/post` responses for VAPIX 3 responses.

**`pyproject.toml` key sections:**
```toml
[project]
name = "cctv"
requires-python = ">=3.11"
dependencies = ["typer>=0.24", "requests>=2.33", "pyyaml>=6.0"]

[project.optional-dependencies]
dev = ["pytest>=9.0"]

[project.scripts]
cctv = "cctv.cli:app"

[build-system]
requires = ["setuptools>=68"]
build-backend = "setuptools.backends.legacy:build"
```

## Architecture Validation Results

### Coherence Validation ✅

**Decision Compatibility:** All technology choices are mutually compatible. Python 3.11+ type hints are required by Typer and supported by all selected libraries. `requests.auth.HTTPDigestAuth` is built into `requests` — no extra dependency for VAPIX auth. `ThreadPoolExecutor` is stdlib — no dependency for concurrency. No version conflicts identified.

**Pattern Consistency:** Module boundary rules (requests in `vapix.py` only, print in `reporter.py` only) are consistent with the project structure and the `CameraResult` data flow. The read-before-write pattern in `reconciler.py` aligns with the idempotency NFR.

**Structure Alignment:** The 8-module structure maps cleanly to the 6 FR categories. All patterns are supported by the chosen stack.

### Requirements Coverage Validation ✅

**Functional Requirements:** All 27 FRs are architecturally covered. Full mapping documented in Project Structure section.

**Non-Functional Requirements:**
- Performance: ThreadPoolExecutor + configurable timeout covers the <30s / <60s NFRs ✓
- Security: Credentials in `CameraConfig` dataclass, never passed to `reporter.py`, HTTPDigestAuth via `requests` ✓
- Reliability: Per-camera try/except in `executor.py`, timeout from config throughout ✓

### Gap Analysis Results

**Critical gap resolved — `model` field in `CameraResult`:**

The scanner must return `list[DiscoveredCamera]` (not `list[str]`) to preserve model info from the VAPIX identification probe:

```python
# In scanner.py
@dataclass
class DiscoveredCamera:
    ip: str
    model: str  # e.g. "AXIS P3245-V"
```

Data flow updated: `scanner.py` → `cli.py` → `executor.py` → `CameraResult.model`.

**Known unknown — VAPIX 3 parameter names:**
The exact `root.Network.Share.*` and `root.Motion.*` parameter names on firmware 5.51.7.4 must be confirmed against real hardware before `vapix.py` is written. Flagged as pre-implementation verification task.

### Architecture Completeness Checklist

- [x] Project context thoroughly analyzed
- [x] Scale and complexity assessed
- [x] Technical constraints identified
- [x] Cross-cutting concerns mapped
- [x] Critical decisions documented with verified versions
- [x] Technology stack fully specified
- [x] VAPIX protocol and firmware target specified
- [x] Concurrency model decided (ThreadPoolExecutor)
- [x] Error/result model defined (CameraResult + CameraStatus + DiscoveredCamera)
- [x] Naming conventions established
- [x] Module boundary rules defined and enforced
- [x] Anti-patterns documented
- [x] Complete directory structure defined
- [x] Component boundaries established
- [x] Data flow documented
- [x] FR-to-file mapping complete

### Architecture Readiness Assessment

**Overall Status:** READY FOR IMPLEMENTATION

**Confidence Level:** High — low-complexity tool, clear module boundaries, all FRs mapped, single known unknown (VAPIX param names) appropriately flagged.

**Key Strengths:**
- Clean separation of concerns — each module has one job and one owner
- Testable without network — only `vapix.py` touches `requests`; everything else is pure logic
- Idempotency is structural — read-before-write enforced in `reconciler.py`
- `CameraResult` dataclass makes failure isolation explicit and type-safe

**Areas for Future Enhancement:**
- asyncio migration if fleet size demands it
- `--output json` for scripting (Phase 2)
- PyPI release (Phase 2)

### Implementation Handoff

**First implementation priority:** `pyproject.toml` scaffold + `config.py` (no network dependency — validates the data model before touching hardware).

**Pre-implementation task:** Verify exact VAPIX 3 parameter names for SMB and motion detection on firmware 5.51.7.4 against a real camera before writing `vapix.py`.

**All agents must:** Follow module boundary rules, use `CameraResult`/`DiscoveredCamera` dataclasses, never hardcode timeouts, never print outside `reporter.py`.
