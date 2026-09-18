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
FR28: The system can detect whether the AXIS Video Motion Detection app is installed and running on a camera, and — for legacy cameras where it doesn't ship pre-installed — install it from a local `.eap` package path specified in config before configuring motion detection.
FR29: The operator can run `cctv status <config.yaml>` to see the current live VAPIX state of each discovered camera without applying any changes.
FR30: The system can report each camera's motion detection app installation/running status and its configured window(s)/sensitivity.
FR31: The system can report each camera's configured action rules (events) together with their linked action configuration (trigger condition, target action, pre/post duration).
FR32: The system can report each camera's configured SMB/network share settings (IP, share path, username) excluding passwords.
FR33: The system can report each camera's current timezone and recording retention (cleanup max age) setting.
FR34: The operator can request `cctv status` output as JSON via a `--json` flag for machine-readable consumption.
FR35: The system can link the motion-detection action rule to the actual motion source in use on a camera — the installed AXIS Video Motion Detection app's own event topic on legacy cameras where that app had to be installed, rather than assuming the fixed built-in window-based motion topic applies to every camera.
FR36: The operator can define multiple named profiles in the config file, each matching one or more camera models.
FR37: The system can match a discovered camera to the first profile whose configured models list matches the camera's reported model string.
FR38: The system can report a camera as failed, distinctly from a VAPIX error, when it matches no configured profile.
FR39: The operator can pin a `target_firmware` version per profile; the system checks it before applying any other setting and fails that camera (applying nothing) on a mismatch.
FR40: The system never upgrades or otherwise modifies camera firmware — `target_firmware` is a read-only precondition.
FR41: The operator can select a storage backend per profile (`smb` or `sd_s3sync`), each with its own destination settings.
FR42: The system can install and configure the `sd_to_s3_sync` ACAP from a local package path, writing configuration before first start and restarting the app when its configuration changed, since it reads configuration only at process startup.
FR43: The system can configure the built-in VMD4 motion-detection engine (filter-based) as an alternative to the legacy sensitivity-based motion group, selected by matched profile.
FR44: The operator can define fleet-wide settings (NTP fallback servers, timezone, recording retention) once, applied identically to every camera regardless of profile.
FR45: The system can configure recording retention against the correct underlying storage group (SD card vs. network share) per the matched profile's backend.
FR46: The system can ensure a motion→record action rule exists on each camera, binding the profile's motion event source to a recording action targeting that profile's storage.
FR47: The system can bind the `sd_s3sync` recording rule to the camera's actual VMD4 profile identifier rather than the "any profile" wildcard, which the rule-creation API rejects.
FR48: The system can converge an existing but incorrect action rule by removing and recreating it, since the API offers no in-place edit; a disabled rule does not count as satisfying the requirement.
FR49: The system can expand the built-in VMD4 detection profile's trigger area to cover the full frame, preserving filters, identifiers, and other trigger types.
FR50: The system can synchronise a camera's DHCP-assigned hostname onto its static hostname, because the hostname determines each camera's namespace within shared storage.
FR51: The system deliberately does not manage the sync ACAP's S3 key prefix — the ACAP derives it from the camera's own hostname at runtime.

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
- **Verified parameter names (resolved):** the SMB group is `root.NetworkShare.N0.*` and legacy motion is `root.Motion.M<n>.*`, both confirmed on firmware 5.51.7.4. Neither exists usably on 12.x — see the VAPIX API Protocol section of `architecture.md` for the full verified parameter table across both generations.
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
FR28: Epic 3 — detect/install AXIS Video Motion Detection app on legacy cameras before configuring motion detection (Story 3.6)
FR29: Epic 4 — `cctv status` read-only fleet status report (Story 4.1)
FR30: Epic 4 — report motion detection app status + window/sensitivity (Story 4.1)
FR31: Epic 4 — report action rules (events) + linked action configuration (Story 4.1)
FR32: Epic 4 — report SMB/network share settings, excluding passwords (Story 4.1)
FR33: Epic 4 — report timezone + recording retention (Story 4.1)
FR34: Epic 4 — `--json` output flag for `cctv status` (Story 4.2)
FR35: Epic 3 — link motion action rule to the installed VMD app's own event topic on legacy cameras (Story 3.7)
FR36: Epic 5 — multiple named profiles matched by camera model (Story 5.1)
FR37: Epic 5 — first-match-wins profile selection by model substring (Story 5.1)
FR38: Epic 5 — camera matching no profile is reported failed, not skipped (Story 5.1)
FR39: Epic 5 — `target_firmware` precondition checked before any write (Story 5.2)
FR40: Epic 5 — firmware never upgraded by the tool (Story 5.2)
FR41: Epic 5 — storage backend selected per profile (Stories 5.1, 5.3)
FR42: Epic 5 — sync ACAP install, configure-before-start, restart-on-change (Story 5.3)
FR43: Epic 5 — VMD4 filter-based motion configuration (Story 5.4)
FR44: Epic 5 — fleet-wide NTP, timezone, retention (Story 5.6)
FR45: Epic 5 — retention routed to the backend's storage group (Story 5.6)
FR46: Epic 5 — motion→record action rule for both backends (Story 5.5)
FR47: Epic 5 — concrete VMD4 profile topic, not the wildcard (Story 5.5)
FR48: Epic 5 — remove-and-recreate convergence of incorrect rules (Story 5.5)
FR49: Epic 5 — VMD4 trigger area expanded to full frame (Story 5.4)
FR50: Epic 5 — DHCP hostname synced to static hostname (Story 5.6)
FR51: Epic 5 — S3 key prefix deliberately unmanaged (Story 5.3)

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

**FRs covered:** FR12, FR13, FR14, FR15, FR16, FR17, FR18, FR19, FR20, FR21, FR22, FR23, FR24, FR25, FR26, FR28, FR35
**NFRs addressed:** NFR2, NFR3, NFR7, NFR9, NFR10, NFR11, NFR12, NFR13

### Epic 4: Camera Fleet Status Reporting (`cctv status`)
The user can run a strictly read-only command that reports each discovered camera's live VAPIX state — motion detection app + settings, action rules/events, SMB share config, timezone, and recording retention — as a quick way to audit the fleet without cross-referencing `cameras.yaml` against multiple camera web UIs. Never calls any write/SET/SOAP-mutation VAPIX endpoint.

**FRs covered:** FR29, FR30, FR31, FR32, FR33, FR34
**NFRs addressed:** NFR3, NFR7, NFR8

### Epic 5: Camera Profiles and the SD+S3 Backend (added 2026-09-02)
The user can manage a fleet spanning two camera generations from one config file. Each camera is matched by model to a named profile that declares its own firmware precondition, motion-detection method, storage backend, and required applications — while NTP, timezone, and retention stay declared once, fleet-wide. This exists because the AXIS M3085-V generation supports neither SMB shares nor the legacy motion parameter group, and needs SD-card recording plus a sync ACAP instead.

**FRs covered:** FR36, FR37, FR38, FR39, FR40, FR41, FR42, FR43, FR44, FR45, FR46, FR47, FR48, FR49, FR50, FR51
**NFRs addressed:** NFR3, NFR7, NFR9, NFR11

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

**FRs covered:** FR12, FR13, FR14, FR15, FR16, FR17, FR18, FR19, FR20, FR21, FR22, FR23, FR24, FR25, FR26, FR28, FR35
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

### Story 3.6: Legacy Camera VMD App Detection and Install

As a home sysadmin,
I want the tool to detect whether the AXIS Video Motion Detection app is installed on a camera and install it from a local `.eap` package if it's missing,
So that motion detection can be configured on legacy cameras that don't ship with the app pre-installed, without a manual VAPIX/SOAP workaround per camera.

**Acceptance Criteria:**

**Given** `motion_detection.enabled: true` in config and the AXIS Video Motion Detection app is not present in the camera's installed-applications list
**When** `cctv apply` runs and `motion_detection.app_package_path` is set in config
**Then** the `.eap` file at that path is uploaded and installed on the camera via VAPIX
**And** the app is started using whatever package `Name` the camera assigns it (not assumed to be a fixed string — different `.eap` versions register under different internal names, e.g. `vmd` vs `VideoMotionDetection`)
**And** `motion_app_installed` is included in `CameraResult.settings_changed`

**Given** the app is not installed and `motion_detection.app_package_path` is not set in config
**When** `cctv apply` runs
**Then** a clear `VapixError` is raised naming the camera IP and the missing config key, and no upload is attempted

**Given** the app is already installed but its Status is `Stopped`
**When** `cctv apply` runs
**Then** the app is started via VAPIX (not re-uploaded)
**And** `motion_app_started` is included in `CameraResult.settings_changed`

**Given** the app is already installed and its Status is anything other than `Stopped` (e.g. `Running` or `Idle`)
**When** `cctv apply` runs
**Then** no install or start call is made, and the run is idempotent

### Story 3.7: Legacy VMD App Event-Linked Action Rule

As a home sysadmin,
I want the motion-detection action rule on a legacy camera to trigger from the installed AXIS Video Motion Detection app's own event, not from a fixed built-in motion topic,
So that recordings actually fire on cameras where `root.Motion` is only populated because Story 3.6 installed the app, instead of the rule silently assuming a built-in motion topic that may not apply to that app/firmware combination.

**Acceptance Criteria:**

**Given** `cctv apply` found the AXIS Video Motion Detection app already installed or had to install it this run (i.e. the camera needed the app to expose motion at all — the Story 3.6 install path)
**When** the motion detection action rule is created or updated
**Then** the rule's condition topic targets the installed app's own event topic, not the generic window-based `tns1:VideoAnalytics/tnsaxis:MotionDetection` topic used for cameras with native built-in motion

**Given** a camera exposes `root.Motion` natively and never required the VMD app install step (built-in motion detection, per Story 3.1/3.3)
**When** the motion detection action rule is created or updated
**Then** the existing window-based topic behaviour is unchanged — this story only changes the topic used on the legacy-app-install path

**Given** the exact event topic string published by `AXIS_Video_Motion_Detection_2_2_1.eap` has not yet been confirmed against real hardware
**When** this story is implemented
**Then** the topic constant is added marked `UNVERIFIED`, following the same pattern as `_MOTION_GROUP`/`_SMB_GROUP` before their Story 1.4/3.3 hardware verification, and the story cannot move to `done` until a real `cctv apply` run against a legacy camera is followed by an actual motion event and confirmed recording (not just a green mocked test suite — see Story 3.6's Dev Notes on hardware-only bugs the mocked suite missed)

## Epic 4: Camera Fleet Status Reporting (`cctv status`)

The user can run a strictly read-only command that reports each discovered camera's live VAPIX state — motion detection app + settings, action rules/events, SMB share config, timezone, and recording retention — as a quick way to audit the fleet without cross-referencing `cameras.yaml` against multiple camera web UIs. `status` never calls any write/SET/SOAP-mutation VAPIX endpoint; it is exactly as safe to run as `cctv list`.

**FRs covered:** FR29, FR30, FR31, FR32, FR33, FR34
**NFRs addressed:** NFR3, NFR7, NFR8

### Story 4.1: Camera Status Collection and Text Report

As a home sysadmin,
I want `cctv status <config.yaml>` to print each discovered camera's current motion detection, action rules, SMB share, timezone, and retention settings,
So that I can audit my fleet's live state from the terminal without opening any camera's web UI.

**Acceptance Criteria:**

**Given** a valid `cameras.yaml` and reachable cameras on the configured subnet
**When** I run `cctv status cameras.yaml`
**Then** every discovered camera is probed read-only (no `set_params`, `add_action_rule`, `add_action_configuration`, `upload_application`, or `start_application` call is ever made)
**And** for each camera the output includes: motion app name/nice-name/status, motion enabled state + sensitivity + window extent, all configured action rules with their linked action configuration (name, trigger topic, target template, pre/post duration), SMB share IP/path/username (never password), current timezone, and recording retention in days

**Given** a camera is unreachable or a VAPIX call for one camera fails mid-collection
**When** `cctv status` runs across a multi-camera fleet
**Then** that camera's block reports the failure reason (mirroring `CameraResult.status == FAILED` semantics from Epic 3) and the remaining cameras are still reported — one bad camera does not abort the whole run

**Given** `--subnet <CIDR>` is passed
**When** `cctv status cameras.yaml --subnet <CIDR>` runs
**Then** the override subnet is used for discovery instead of the one in the config file (same behaviour as `list`/`apply`)

**Given** no cameras are found on the subnet
**When** `cctv status` completes
**Then** the output states no cameras were found and the process exits with code 2 (same convention as `cctv list`)

### Story 4.2: JSON Output for `cctv status`

As a home sysadmin,
I want a `--json` flag on `cctv status`,
So that I can pipe fleet status into scripts or other tooling instead of parsing text.

**Acceptance Criteria:**

**Given** `cctv status cameras.yaml --json` is run
**When** the command completes
**Then** stdout is a single JSON array, one object per camera, with the same fields as the text report (motion, action rules, smb, timezone, retention) using stable, documented key names
**And** no plaintext/human-formatted status lines are mixed into stdout — errors and diagnostics still go to stderr per NFR7/FR26

**Given** a camera fails during collection
**When** `--json` output is produced
**Then** that camera's JSON object includes an `error` field describing the failure, consistent with the text report's failure case in Story 4.1

**Given** `--json` is not passed
**When** `cctv status` runs
**Then** output is the human-readable text format from Story 4.1 (JSON is opt-in, not the default)

## Epic 5: Camera Profiles and the SD+S3 Backend

The user can manage a fleet spanning two camera generations from one config
file. Each camera is matched by model to a named profile declaring its own
firmware precondition, motion-detection method, storage backend, and required
applications; NTP, timezone, and retention stay declared once, fleet-wide.

**Why this epic exists:** the AXIS M3085-V generation (AXIS OS 12.x) supports
neither SMB network shares (`root.NetworkShare` errors outright) nor the legacy
motion parameter group (`root.Motion` is unused by VMD4). The single implicit
profile assumed by Epics 1–3 could not be stretched to cover it. See the VAPIX
API Protocol section of `architecture.md` for the per-generation API details
these stories depend on.

**FRs covered:** FR36–FR51
**NFRs addressed:** NFR3, NFR7, NFR9, NFR11

### Story 5.1: Profile-Based Config Schema and Model Matching

As a home sysadmin,
I want to declare multiple named profiles in `cameras.yaml`, each matching a set of camera models,
So that one config file can describe a fleet whose cameras need genuinely different settings.

**Acceptance Criteria:**

**Given** a config file with a `profiles` list, each entry having `name`, `match.models`, `motion_detection`, and `storage`
**When** the config is loaded
**Then** each profile is parsed into its own structure, and validation errors name the offending profile by index and full key path (e.g. `profiles[1].storage.sd_s3sync.secret_key`)

**Given** a discovered camera reporting a full product name such as `AXIS M3085-V Network Camera`
**When** it is matched against a profile whose `match.models` contains `M3085-V`
**Then** the profile matches on substring, not exact equality

**Given** a camera matching more than one profile's model list
**When** matching runs
**Then** the first profile declared in the file wins — declaration order is the tiebreak, not specificity

**Given** a camera matching no profile at all
**When** `cctv apply` reaches it
**Then** that camera is reported as failed with a message naming its model and pointing at `match.models`, and no setting is read or written on it — an unmanaged camera is visible in the output, never silently skipped

**Given** fleet-wide keys (`ntp_fallback_servers`, `timezone`, `recording_retention_days`)
**When** they are present at the top level
**Then** they apply to every camera regardless of matched profile, and each is independently optional

### Story 5.2: Firmware Precondition Check

As a home sysadmin,
I want a profile to pin the firmware version its settings were verified against,
So that cctv refuses to configure a camera whose API surface may not match what the profile assumes.

**Acceptance Criteria:**

**Given** a profile declaring `target_firmware`
**When** a matched camera reports a different firmware version
**Then** that camera fails with a message stating both versions and that cctv does not auto-upgrade, **before any other setting is read or written** — the camera is never left partially converged

**Given** a profile with no `target_firmware`
**When** reconciliation runs
**Then** the firmware version parameter is never read at all

**Given** any camera in any state
**When** cctv runs
**Then** no firmware upgrade call is ever issued — `target_firmware` is a read-only precondition (see the rejected-alternatives section of `architecture.md` for the real-hardware upgrade failure that settled this)

### Story 5.3: SD-Card + S3 Sync Storage Backend

As a home sysadmin,
I want cameras that cannot use SMB to record to their SD card and have clips synced to an S3 bucket,
So that the newer camera generation gets off-camera storage without a network share it cannot mount.

**Acceptance Criteria:**

**Given** a profile with `storage.backend: sd_s3sync`
**When** reconciliation runs against a matched camera
**Then** the SMB parameter group and the legacy motion group are never read or written on that camera

**Given** the sync ACAP is not installed and the profile declares `applications.sd_to_s3_sync.app_package_path`
**When** reconciliation runs
**Then** the package is uploaded, the application list is re-read to learn the registered package name, and a failure to appear afterwards is reported as a clear error

**Given** the ACAP is absent and no `app_package_path` is configured
**When** reconciliation runs
**Then** the camera fails with a message naming the missing config key — no silent skip

**Given** the ACAP's stored S3 configuration differs from the profile
**When** reconciliation runs
**Then** only the differing parameters are written, not the whole group

**Given** the ACAP is running and its configuration was just changed
**When** reconciliation completes that step
**Then** the app is stopped and started again, because it reads configuration only at process startup and would otherwise keep running with the old values

**Given** the ACAP is running and its configuration did not change
**When** reconciliation runs
**Then** it is left alone — no restart that would interrupt an in-flight upload

**Given** the ACAP is installed but stopped, with configuration already correct
**When** reconciliation runs
**Then** it is simply started

**Given** any reconciliation of this backend
**When** ACAP parameters are written
**Then** the S3 key prefix is never among them — the app derives it from the camera's own hostname, giving each camera its own bucket namespace with no per-camera config

### Story 5.4: VMD4 Motion Configuration

As a home sysadmin,
I want motion detection configured correctly on the VMD4 camera generation,
So that motion anywhere in frame raises an event with the same tuning as the reference camera.

**Acceptance Criteria:**

**Given** a matched camera whose profile uses VMD4 motion
**When** the bundled motion application is `Stopped`
**Then** it is started — and never installed from a package, since it ships with the firmware on this generation

**Given** the motion application is entirely absent on such a camera
**When** reconciliation runs
**Then** the camera fails with a message saying the app was expected to be bundled — cctv does not attempt to install it

**Given** the detection profile's trigger area does not cover the full frame
**When** reconciliation runs
**Then** the trigger area is expanded to full frame, and the profile's filters, identifier, name, and any other trigger types are preserved unchanged

**Given** the profile declares filter values (minimum object size, short-lived-object limit, swaying-object distance)
**When** the camera's corresponding filters differ
**Then** those filters are updated in place; filter types not already present on the camera are not invented

**Given** the profile sets `motion_detection.enabled: false`
**When** reconciliation runs
**Then** no motion API is called at all, but the storage backend is still converged

### Story 5.5: Motion→Record Action Rule for Both Backends

As a home sysadmin,
I want the motion event bound to a recording action on every camera,
So that configured cameras actually record, rather than being fully configured but inert.

**Acceptance Criteria:**

**Given** a camera with no motion recording rule
**When** reconciliation runs
**Then** an action configuration and an action rule are created in that order, the rule referencing the returned configuration id, with the profile's pre/post durations converted to milliseconds

**Given** the `sd_s3sync` backend
**When** the rule is created
**Then** it targets storage `SD_DISK` and is bound to the camera's actual VMD4 profile identifier — never the "any profile" wildcard, which the rule-creation API rejects even though it appears when reading existing rules back

**Given** the `smb` backend
**When** the rule is created
**Then** it targets storage `NetworkShare`, bound to the legacy application's own event topic when that application is the motion source, otherwise to the built-in motion topic narrowed to the full-frame window

**Given** an existing enabled rule whose topic, storage target, or durations do not match the desired state
**When** reconciliation runs
**Then** both the rule and its action configuration are removed and recreated, because the API offers no in-place edit of an action configuration

**Given** an existing rule that is already fully correct
**When** reconciliation runs
**Then** nothing is created or removed

**Given** a rule that matches in every respect but is disabled
**When** reconciliation runs
**Then** it does not count as satisfying the requirement and a correct rule is created

### Story 5.6: Fleet-Wide Time and Retention Settings

As a home sysadmin,
I want NTP, timezone, and retention declared once and applied everywhere,
So that settings which should never differ between cameras cannot drift apart per profile.

**Acceptance Criteria:**

**Given** `ntp_fallback_servers` is configured
**When** the camera's configured list differs
**Then** the full intended list is written in one replace operation — never appended to, since a partial write drops the servers omitted from it

**Given** `ntp_fallback_servers` is absent or empty
**When** reconciliation runs
**Then** the NTP endpoint is never read

**Given** `recording_retention_days` is configured
**When** reconciliation runs
**Then** it is written to the storage group matching the camera's backend — the SD card group on `sd_s3sync`, the network-share group on `smb` — from that single fleet-wide value

**Given** a camera whose DHCP-assigned hostname differs from its configured static hostname
**When** reconciliation runs
**Then** the static hostname is synced to it, because that hostname determines the camera's own namespace in shared storage

**Given** a camera with no DHCP-assigned hostname
**When** reconciliation runs
**Then** the hostname is left unchanged and the static hostname is not even read
