---
stepsCompleted: ['step-01-validate-prerequisites', 'step-02-design-epics', 'step-03-create-stories', 'step-04-final-validation']
inputDocuments: ['_bmad-output/planning-artifacts/prd.md', '_bmad-output/planning-artifacts/architecture.md']
---

# cctv - Epic Breakdown

## Overview

This document provides the complete epic and story breakdown for cctv, decomposing the requirements from the PRD and Architecture requirements into implementable stories.

## Requirements Inventory

### Functional Requirements

FR1: The operator can trigger a scan of a configured IP subnet to discover all reachable Axis cameras.
FR2: The operator can view a list of discovered cameras showing IP address and camera model without making any configuration changes.
FR3: The operator can override the default subnet at runtime without modifying the config file.
FR4: The system can identify Axis cameras on a subnet by probing each IP in the configured CIDR range via HTTP.
FR5: The operator can discover cameras independently of applying configuration (read-only operation).
FR6: The operator can define desired camera state in a YAML configuration file.
FR7: The operator can specify camera login credentials (username, password) in the config file.
FR8: The operator can specify SMB share settings (IP, share path, SMB username, SMB password) in the config file.
FR9: The operator can specify motion detection settings (enabled/disabled, sensitivity) in the config file.
FR10: The operator can specify the target subnet in the config file.
FR11: The system can validate the config file structure and report specific parse errors before attempting any camera operations.
FR12: The operator can apply a config file to all discovered cameras in a single command.
FR13: The system can read the current value of each managed setting from a camera before deciding whether to apply a change.
FR14: The system can skip applying a setting to a camera when the current value already matches the desired state.
FR15: The system can apply configuration changes to multiple cameras in sequence without aborting when one camera fails.
FR16: The system can apply the same config file multiple times and produce the same end state with no errors on subsequent runs (idempotency).
FR17: The system can configure the SMB share IP address on an Axis camera via the VAPIX API.
FR18: The system can configure the SMB share path and credentials on an Axis camera via the VAPIX API.
FR19: The system can enable or disable built-in motion detection on an Axis camera via the VAPIX API.
FR20: The system can configure motion detection sensitivity on an Axis camera via the VAPIX API.
FR21: The operator can see per-camera outcome after an apply run: one of `applied`, `no change`, or `FAILED` for each discovered camera.
FR22: The operator can see which specific settings were applied or skipped for each camera in the apply output.
FR23: The operator can see a summary line at the end of an apply run with counts of applied, no-change, and failed cameras.
FR24: The operator can see an actionable error message when a camera fails, including the camera IP and the reason for failure.
FR25: The system can exit with code `0` when all cameras succeed (applied or no-change), `1` when one or more cameras fail, and `2` on a fatal error.
FR26: The system can write all error and diagnostic output to stderr, keeping stdout clean for status output.
FR27: The operator can see the count of cameras found during a `cctv list` run along with their IPs and models.

### NonFunctional Requirements

NFR1: `cctv list` on a /24 subnet completes within 30 seconds under normal network conditions.
NFR2: `cctv apply` completes within 60 seconds for a fleet of up to 10 cameras under normal network conditions.
NFR3: Per-camera connection timeout is configurable (default: 5 seconds) to prevent a single unreachable host from blocking the entire run.
NFR4: Camera probing during discovery is parallelised or time-bounded to avoid O(n) sequential blocking on large subnets.
NFR5: Camera credentials and SMB credentials are stored in plaintext in the config YAML — explicit documented trade-off for v1.
NFR6: The README warns that the config file contains plaintext credentials and advises against committing it to public repositories.
NFR7: Credentials never appear in stdout/stderr output.
NFR8: All VAPIX API communication uses HTTP Digest Authentication as provided by the Axis camera.
NFR9: The tool does not store credentials beyond the lifetime of a single run (no credential caching, no keychain integration).
NFR10: A connection failure to one camera does not affect configuration of remaining cameras in the same run.
NFR11: A camera that does not respond within the configured timeout is marked `FAILED`, not left hanging.
NFR12: The tool exits with a documented, non-zero exit code on any failure condition, enabling reliable use in shell scripts.
NFR13: VAPIX API errors (non-2xx responses) are captured and surfaced as actionable error messages, not silently ignored.

### Additional Requirements

- **Project scaffold:** Python 3.11+, Typer 0.24.1, requests 2.33.1, pyyaml 6.0.3, pytest 9.0.2. `src/` layout. `pyproject.toml` only (no setup.py). Entry point: `cctv = "cctv.cli:app"`.
- **Module boundary rules:** `import requests` only in `vapix.py`; `print()` / `sys.stdout.write()` only in `reporter.py`; no exceptions.
- **Dataclasses required:** `CameraConfig`, `CameraResult` (with `CameraStatus` enum), `DiscoveredCamera` — defined before coding module logic.
- **Exception hierarchy:** `VapixError` defined in `vapix.py`; `ConfigError` defined in `config.py`. Executor catches all exceptions per camera.
- **Read-before-write enforcement:** `reconciler.py` must always GET current state before any SET; never call `set_params` without comparing current state first.
- **Timeout discipline:** Always pass `timeout` from `CameraConfig` — never hardcode a timeout value in any module.
- **Pre-implementation verification task:** Exact VAPIX 3 parameter names for SMB (`root.Network.Share.*`) and motion detection (`root.Motion.*`) on firmware 5.51.7.4 must be verified against real hardware before coding `vapix.py`.
- **Distribution:** `pip install git+https://github.com/atotmakov/cctv.git`; development mode via `pip install -e .`.
- **Implementation sequence:** pyproject.toml scaffold → config.py → vapix.py → scanner.py → reconciler.py → executor.py → reporter.py → cli.py.
- **Test fixtures:** `conftest.py` must provide a sample `CameraConfig`, mock `HTTPDigestAuth`, and mock `requests.get/post` responses for VAPIX 3 responses.
- **Reference config:** `cameras.yaml.example` committed to git; actual `cameras.yaml` gitignored (contains plaintext credentials).

### UX Design Requirements

N/A — CLI tool. No UX Design document.

### FR Coverage Map

FR1: Epic 2 — trigger subnet scan to discover Axis cameras
FR2: Epic 2 — view discovered cameras with IP and model (read-only)
FR3: Epic 2 — override subnet at runtime via --subnet flag
FR4: Epic 2 — HTTP probe to identify Axis cameras in CIDR range
FR5: Epic 2 — discovery operates independently from apply (no side effects)
FR6: Epic 1 — define desired camera state in YAML config file
FR7: Epic 1 — specify camera login credentials in config
FR8: Epic 1 — specify SMB share settings in config
FR9: Epic 1 — specify motion detection settings in config
FR10: Epic 1 — specify target subnet in config
FR11: Epic 1 — validate config structure and report parse errors before camera ops
FR12: Epic 3 — apply config to all discovered cameras in one command
FR13: Epic 3 — read current camera state before deciding to apply (Story 3.1)
FR14: Epic 3 — skip setting when current value already matches desired state (Story 3.1)
FR15: Epic 3 — continue applying to remaining cameras when one fails (Story 3.2)
FR16: Epic 3 — same config applied twice produces same end state, no errors (Story 3.1)
FR17: Epic 3 — configure SMB share IP via VAPIX API (Story 3.2)
FR18: Epic 3 — configure SMB share path and credentials via VAPIX API (Story 3.2)
FR19: Epic 3 — enable/disable motion detection via VAPIX API (Story 3.3)
FR20: Epic 3 — configure motion detection sensitivity via VAPIX API (Story 3.3)
FR21: Epic 3 — per-camera outcome: applied / no change / FAILED
FR22: Epic 3 — which specific settings were applied or skipped, per camera
FR23: Epic 3 — summary line with counts of applied / no-change / failed cameras
FR24: Epic 3 — actionable error message with camera IP and failure reason
FR25: Epic 3 — exit code 0 (all ok), 1 (partial failure), 2 (fatal error)
FR26: Epic 3 — errors and diagnostics to stderr; stdout clean for status output
FR27: Epic 2 — count of cameras found during list run, with IPs and models

## Epic List

### Epic 1: Installable Tool with Config Validation
The user can install `cctv`, define their camera fleet's desired state in a YAML file, get immediate feedback if the config is invalid, and have a working VAPIX API client ready for discovery and apply — all before touching any camera.

**FRs covered:** FR6, FR7, FR8, FR9, FR10, FR11
**NFRs addressed:** NFR3, NFR5, NFR6, NFR8

### Epic 2: Camera Fleet Discovery (`cctv list`)
The user can scan their subnet and see a list of all reachable Axis cameras with their IP and model — a fully read-only, no-side-effects operation usable as a pre-flight check before applying config.

**FRs covered:** FR1, FR2, FR3, FR4, FR5, FR27
**NFRs addressed:** NFR1, NFR3, NFR4, NFR8

### Epic 3: Idempotent Configuration Convergence (`cctv apply`)
The user can apply their config to all discovered cameras in a single command. Cameras already at desired state are skipped. One offline camera doesn't abort the rest. Output tells the user exactly what happened, per camera, per setting. Safe to re-run at any time.

**FRs covered:** FR12, FR13, FR14, FR15, FR16, FR17, FR18, FR19, FR20, FR21, FR22, FR23, FR24, FR25, FR26
**NFRs addressed:** NFR2, NFR3, NFR7, NFR9, NFR10, NFR11, NFR12, NFR13

## Epic 1: Installable Tool with Config Validation

The user can install `cctv`, define their camera fleet's desired state in a YAML file, and get immediate feedback if the config is invalid — before any camera is touched. The config file becomes the version-controllable infrastructure artifact.

**FRs covered:** FR6, FR7, FR8, FR9, FR10, FR11
**NFRs addressed:** NFR5, NFR6

### Story 1.1: Project Scaffold and Installable CLI

As a home sysadmin,
I want to install `cctv` via pip and run `cctv --help`,
So that I can confirm the tool is installed and see available commands.

**Acceptance Criteria:**

**Given** the repo is cloned and Python 3.11+ is available
**When** I run `pip install -e .`
**Then** the `cctv` entry point is available on PATH
**And** `cctv --help` outputs the available commands (`list`, `apply`) without error

**Given** the project structure follows the src layout
**When** pytest is run
**Then** all test files are discoverable and importable without path errors

### Story 1.2: YAML Config File Loading

As a home sysadmin,
I want to define my camera fleet's desired state in a `cameras.yaml` file,
So that I have a single, version-controllable source of truth for all camera settings.

**Acceptance Criteria:**

**Given** a valid `cameras.yaml` with all required keys (subnet, credentials, smb, motion_detection)
**When** `config.py` parses it
**Then** a `CameraConfig` dataclass is returned with all fields correctly populated
**And** the `timeout` field defaults to 5 seconds if not specified in the YAML

**Given** `cameras.yaml.example` is present in the repository
**When** I review its contents
**Then** all config keys are documented with example values
**And** the `.gitignore` excludes `cameras.yaml` to protect plaintext credentials

### Story 1.3: Config Validation with Actionable Error Reporting

As a home sysadmin,
I want clear, specific error messages when my config file is missing or malformed,
So that I can fix it immediately without debugging the tool.

**Acceptance Criteria:**

**Given** a config file missing a required key (e.g. `smb.ip`)
**When** `cctv` attempts to load it
**Then** a `ConfigError` is raised with a message naming the specific missing key
**And** the process exits with code 2 before attempting any camera operations

**Given** the config file path does not exist
**When** I run `cctv apply nonexistent.yaml`
**Then** an error message is printed to stderr stating the file was not found
**And** the process exits with code 2

**Given** a config file with an invalid subnet value (not a valid CIDR)
**When** `cctv` attempts to load it
**Then** a `ConfigError` is raised identifying the invalid value
**And** the process exits with code 2

### Story 1.4: VAPIX API Client (Get and Set Parameters)

As a home sysadmin,
I want the tool to communicate with Axis cameras via the VAPIX 3 API,
So that it can read and write camera settings reliably using HTTP Digest Auth.

**Acceptance Criteria:**

**Given** a reachable Axis camera at a known IP
**When** `get_params(ip, group, auth, timeout)` is called
**Then** the current parameter values for that group are returned as `dict[str, str]`
**And** HTTP Digest Auth is used on every request

**Given** a VAPIX SET call receives a non-2xx response
**When** `set_params(ip, params, auth, timeout)` is called
**Then** a `VapixError` is raised with the response status and reason
**And** no raw credential values appear in the error message

**Given** the camera does not respond within the configured timeout
**When** any VAPIX call is made
**Then** a `VapixError` is raised (connection timeout)
**And** the hardcoded timeout is never used — timeout always comes from `CameraConfig`

## Epic 2: Camera Fleet Discovery (`cctv list`)

The user can scan their subnet and see a list of all reachable Axis cameras with their IP and model — a fully read-only, no-side-effects operation usable as a pre-flight check before applying config.

**FRs covered:** FR1, FR2, FR3, FR4, FR5, FR27
**NFRs addressed:** NFR1, NFR3, NFR4, NFR8

### Story 2.1: Concurrent Axis Camera Discovery

As a home sysadmin,
I want `cctv list` to scan my subnet and identify all Axis cameras,
So that I know which devices are reachable before running apply.

**Acceptance Criteria:**

**Given** a configured subnet (e.g. `192.168.1.0/24`)
**When** I run `cctv list`
**Then** every IP in the range is probed concurrently via HTTP
**And** hosts that respond to the VAPIX brand probe are identified as Axis cameras
**And** the scan completes within 30 seconds on a /24 subnet under normal conditions

**Given** a host does not respond within the configured timeout (default 5s)
**When** the scanner probes that IP
**Then** that IP is silently skipped (not listed, not errored)
**And** the scan continues to remaining IPs without blocking

### Story 2.2: Discovery Output and `--subnet` Override

As a home sysadmin,
I want to see a clear list of discovered cameras with their IPs and models, and optionally override the subnet,
So that I can quickly verify my fleet's reachability from the command line.

**Acceptance Criteria:**

**Given** Axis cameras are discovered on the subnet
**When** `cctv list` completes
**Then** output shows one line per camera with IP and model (e.g. `192.168.1.101  AXIS P3245-V  (reachable)`)
**And** a count of discovered cameras is shown (e.g. `Found 4 Axis cameras`)
**And** no configuration changes are made to any camera

**Given** I pass `--subnet 10.0.0.0/24`
**When** `cctv list --subnet 10.0.0.0/24` runs
**Then** the scan uses `10.0.0.0/24` instead of the subnet in the config file

**Given** no Axis cameras are found on the subnet
**When** `cctv list` completes
**Then** the output states no cameras were found
**And** the process exits with code 2

## Epic 3: Idempotent Configuration Convergence (`cctv apply`)

The user can apply their config to all discovered cameras in a single command. Cameras already at desired state are skipped. One offline camera doesn't abort the rest. Output tells the user exactly what happened, per camera, per setting. Safe to re-run at any time.

**FRs covered:** FR12, FR13, FR14, FR15, FR16, FR17, FR18, FR19, FR20, FR21, FR22, FR23, FR24, FR25, FR26
**NFRs addressed:** NFR2, NFR3, NFR7, NFR9, NFR10, NFR11, NFR12, NFR13

### Story 3.1: Read-Before-Write State Reconciliation

As a home sysadmin,
I want the tool to check each camera's current settings before applying changes,
So that cameras already at the desired state are never modified unnecessarily.

**Acceptance Criteria:**

**Given** a camera whose SMB IP already matches the config
**When** `reconciler.py` compares desired vs actual state
**Then** `smb_ip` is not included in the change plan
**And** no SET call is made for that parameter

**Given** a camera whose motion sensitivity differs from the config
**When** `reconciler.py` compares desired vs actual state
**Then** `motion_sensitivity` is included in the change plan
**And** `set_params` is called only for parameters that differ

**Given** all three managed settings already match the desired state
**When** reconciliation runs for that camera
**Then** no VAPIX SET calls are made
**And** the camera produces a `CameraResult` with status `NO_CHANGE`

### Story 3.2: SMB Share Configuration via VAPIX

As a home sysadmin,
I want the tool to configure the SMB share IP, path, and credentials on each camera,
So that cameras can store recordings to my NAS automatically.

**Acceptance Criteria:**

**Given** a camera with an outdated SMB IP
**When** `cctv apply` runs
**Then** the SMB IP is updated via VAPIX to match the config value
**And** the change is reflected in `CameraResult.settings_changed` as `smb_ip`

**Given** SMB share path or credentials differ from config
**When** `cctv apply` runs
**Then** the SMB share path and/or credentials are updated via VAPIX
**And** SMB credentials never appear in stdout, stderr, or error messages

### Story 3.3: Motion Detection Configuration via VAPIX

As a home sysadmin,
I want the tool to configure motion detection enabled state and sensitivity on each camera,
So that all cameras have consistent motion detection behaviour without manual UI interaction.

**Acceptance Criteria:**

**Given** motion detection is disabled on a camera but `motion_detection.enabled: true` in config
**When** `cctv apply` runs
**Then** motion detection is enabled on that camera via VAPIX
**And** `motion` is included in `CameraResult.settings_changed`

**Given** motion sensitivity differs from config value
**When** `cctv apply` runs
**Then** motion sensitivity is updated to match the config value via VAPIX

**Given** both motion enabled and sensitivity already match the config
**When** `cctv apply` runs for that camera
**Then** no motion detection SET calls are made

### Story 3.4: Failure-Isolated Apply Executor

As a home sysadmin,
I want one offline or failing camera to not abort the run for other cameras,
So that a partial fleet is still configured when I have a temporarily unreachable device.

**Acceptance Criteria:**

**Given** one camera is unreachable (connection timeout)
**When** `cctv apply` runs across a 4-camera fleet
**Then** the remaining 3 cameras are fully configured
**And** the failed camera produces a `CameraResult` with status `FAILED` and an error message
**And** the error message includes the camera IP and reason (e.g. `connection timeout`)

**Given** a camera returns a VAPIX error during apply
**When** the executor processes that camera
**Then** the exception is caught and converted to `CameraResult(status=FAILED, error=...)`
**And** camera credentials are never included in the error field

### Story 3.5: Per-Camera Output, Summary, and Exit Codes

As a home sysadmin,
I want clear per-camera status output and a summary line after every apply run,
So that I know exactly what happened without needing to inspect anything else.

**Acceptance Criteria:**

**Given** an apply run completes across multiple cameras
**When** results are printed
**Then** each camera produces exactly one output line: `<IP>  <model>  applied (<settings>) | no change | FAILED — <reason>`
**And** a summary line shows counts: `Summary: N applied, M no change, K failed`
**And** all status lines go to stdout; error details go to stderr

**Given** all cameras succeed (applied or no change)
**When** `cctv apply` exits
**Then** the exit code is `0`

**Given** one or more cameras fail
**When** `cctv apply` exits
**Then** the exit code is `1`
**And** the summary line mentions the count of failed cameras with a re-run hint
