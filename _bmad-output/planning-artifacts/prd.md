---
stepsCompleted: ['step-01-init', 'step-01b-continue', 'step-02-discovery', 'step-02b-vision', 'step-02c-executive-summary', 'step-03-success', 'step-04-journeys', 'step-05-domain', 'step-06-innovation', 'step-07-project-type', 'step-08-scoping', 'step-09-functional', 'step-10-nonfunctional', 'step-11-polish', 'step-12-complete']
classification:
  projectType: cli_tool
  domain: general
  complexity: low
  projectContext: greenfield
inputDocuments: ['_bmad-output/planning-artifacts/product-brief-cctv.md']
briefCount: 1
researchCount: 0
brainstormingCount: 0
projectDocsCount: 0
workflowType: 'prd'
---

# Product Requirements Document - cctv

**Author:** atotmakov
**Date:** 2026-03-31
**Amended:** 2026-09-02 — scope expanded from a single implicit camera profile
(SMB + legacy motion) to explicit, per-camera-model **profiles**, after
discovering the newer AXIS M3085-V generation (AXIS OS 12.x) doesn't support
SMB network shares or the legacy motion parameter group at all, and instead
needs SD-card recording plus a third-party S3-sync ACAP. See "Camera
Profiles" and the revised Config Schema below.

## Executive Summary

**cctv** is a Python CLI tool that brings infrastructure-as-code to Axis IP camera fleets. Home sysadmins define desired camera state once in a YAML file; `cctv apply` discovers all Axis cameras on the local subnet, matches each one to a **profile** by model, and converges it to that profile's declared state via the VAPIX API. A profile pairs a motion-detection method with a storage backend (`smb` network-share recording, or `sd_s3sync` — SD card recording synced to S3 by a companion app) — the two backend shapes the author's own fleet actually needs, spanning two AXIS OS generations. Firmware version is a checked *precondition*, never something cctv modifies itself.

The target user is a technically proficient home sysadmin who already operates their network as infrastructure — running Ansible playbooks, Docker Compose stacks, and self-hosted services — but has no declarative option for their cameras. Every configuration change today means clicking through each camera's web UI manually, with no audit trail and inevitable drift. cctv eliminates that entirely.

### What Makes This Special

The core differentiator is the **eventually consistent model**. cctv does not push config once and forget — it declares desired state and converges cameras toward it every time it runs. The same command that configures cameras on day one also corrects drift on day 100. The YAML config file is the artifact: version-controllable, diffable, and reviewable. This is the mental model home sysadmins already use for every other part of their infrastructure; cctv extends it to cameras.

Deliberate opinionation is a feature, not a limitation. Config stays profile-scoped rather than a generic VAPIX wrapper: each profile declares exactly the settings its camera generation needs (motion detection, one storage backend, the apps that back it), plus a small set of fleet-wide settings (NTP fallback, timezone, retention) that apply uniformly regardless of profile. Firmware upgrades are explicitly excluded from what cctv will ever do automatically — real-hardware testing showed a firmware jump can fail and roll back, which is a supervised, one-off operation, not something safe to fold into an unattended convergence loop.

### Camera Profiles

A **profile** is a named block matching one or more camera models (`match.models`, substring-matched against the discovered camera's model string) to a complete desired-state declaration: an optional `target_firmware` precondition, an `applications` map (what needs installing/running), `motion_detection` settings (shape varies by method — see below), and a `storage` block naming exactly one backend.

| | `legacy-smb` | `m3085v-sd-s3sync` |
|---|---|---|
| Camera generation | AXIS OS 5.x (M3005, P1204, M2014-E) | AXIS OS 12.x (M3085-V) |
| Motion detection | Legacy `root.Motion` group + optional install of the legacy VMD `.eap` | Built-in VMD4 (always bundled — never installed), filter-based (`size_percentage`, `time_short_lived_limit`, `distance_swaying_object`) rather than a single sensitivity number |
| Storage backend | `smb` — SMB network share | `sd_s3sync` — SD card, synced off by the `sd_to_s3_sync` ACAP to an S3-compatible bucket |
| Retention semantics | `root.Storage.S1.CleanupMaxAge` | `root.Storage.S0.CleanupMaxAge` |

A camera whose model matches no configured profile is reported as a failure for that run, not silently skipped — an unmanaged camera should be visible in the output, not invisible.

| | |
|---|---|
| **Project Type** | CLI Tool |
| **Domain** | General (home sysadmin / infrastructure tooling) |
| **Complexity** | Low |
| **Project Context** | Greenfield |

## Success Criteria

### User Success

- The user can run `cctv apply config.yaml` and know immediately, from terminal output alone, which cameras were reached, which settings were applied, and which (if any) failed — with no ambiguity.
- A camera already in the desired state produces a clear "no change" signal, not silence.
- A failed camera produces an actionable error: which camera, which setting, what the API returned.

### Business Success

- The tool works reliably and repeatably on the author's own Axis camera fleet without intervention.
- Running `cctv apply` on an already-converged fleet produces zero errors and zero unintended changes.

### Technical Success

- Auto-discovery finds all Axis cameras on the configured subnet without manual IP entry.
- VAPIX API calls for all three managed settings succeed against real Axis hardware.
- Applying the same config twice is a no-op, not an error (idempotency).
- One unreachable camera does not abort the run for remaining cameras (failure isolation).

### Measurable Outcomes

- `cctv apply` on a 4-camera fleet produces per-camera status in terminal output with zero manual follow-up needed.
- Re-running the same config on an already-configured fleet completes with no changes applied and no errors raised.

## Product Scope

### MVP Strategy

**Approach:** Problem-solving MVP — eliminates the manual web-UI configuration workflow for the author's own Axis camera fleet. Solo developer. The tool either solves the problem or it doesn't.

### MVP Feature Set (Phase 1)

**Supports all four user journeys:** first-time fleet setup, drift correction, partial failure recovery, discovery-only pre-flight.

**Must-Have Capabilities:**
- `cctv list` — subnet scan, discover Axis cameras, print IP + model, no side effects
- `cctv apply <config.yaml>` — parse YAML config, discover cameras, match each to a profile by model, converge each to that profile's desired state
- Per-profile settings managed: storage backend (`smb` share IP/credentials, or `sd_s3sync` app install + S3 endpoint/bucket/credentials), motion detection (method + parameters appropriate to that profile), application install/running state
- Fleet-wide settings managed uniformly regardless of profile: NTP fallback servers, timezone, recording retention
- Firmware precondition: a profile may pin `target_firmware`; a mismatch fails that camera before any other setting is touched. cctv never upgrades firmware itself.
- Read-before-write idempotency: check current state before applying, skip if already correct
- Failure isolation: continue applying to remaining cameras if one fails
- Per-camera output: `applied` / `no change` / `FAILED` with error detail and summary line
- Exit codes: 0 (all ok), 1 (partial failure), 2 (fatal error)
- YAML config with plaintext credentials (trade-off documented in README)

### Post-MVP Features (Phase 2)

- `--dry-run` — show what would change without applying
- `--diff` — compare live camera state against config
- `--output json` for scripting and log parsing
- Expanded VAPIX settings: network config, additional motion parameters
  (hostname moved into MVP as FR48 — the `sd_s3sync` backend depends on it,
  since the sync ACAP derives each camera's S3 key prefix from its hostname)
- Shell completion

### Vision (Phase 3)

- Multi-vendor support: ONVIF-compliant cameras, Hikvision, Dahua
- Ansible module wrapper
- Full VAPIX API surface coverage

### Risk Mitigation

**Technical:** VAPIX API behaviour varies across Axis firmware versions and camera generations — confirmed materially different between AXIS OS 5.x and 12.x (different motion-detection APIs, no SMB support at all on 12.x, hidden settings living in modern `/config/rest/...` endpoints that don't show up in the legacy `param.cgi` parameter tree). Test against real hardware before any profile is considered complete — every setting in both current profiles was verified against a live camera, including deliberately triggering a real firmware-upgrade failure to confirm the auto-rollback behavior before deciding firmware upgrades don't belong in cctv at all. No mocking of VAPIX responses in integration tests.

**Scope:** The guardrail is now **profile-scoped** rather than a single fixed setting list: a profile may only manage what's declared for it (one storage backend, its motion-detection method, its own `applications`), plus the fleet-wide settings (NTP fallback, timezone, retention) that apply the same way everywhere. Firmware *upgrading* is out of scope permanently, in every profile — `target_firmware` is a read-only precondition, never a write. Adding a third profile for a new camera generation is expected to happen again; adding scope *within* an existing profile beyond what its real hardware needs is not.

**Resource:** If subnet scanning proves complex, fall back to sequential HTTP probe across the CIDR range rather than adding mDNS/Bonjour dependency.

## User Journeys

### Journey 1: First-Time Fleet Configuration

**Meet Alex.** Alex just wall-mounted four Axis cameras, connected them to the home network, and configured the NAS. The cameras are at their factory defaults. Configuring each one manually through the web UI means opening four browser tabs, logging in four times, navigating to SMB share settings, typing the NAS IP and credentials, enabling motion detection, and repeating. It's 45 minutes of the same clicks.

Alex creates `cameras.yaml`, fills in the NAS IP, SMB credentials, and motion detection parameters once. Runs `cctv list` to verify all four cameras appear — they do. Runs `cctv apply cameras.yaml`.

```
192.168.1.101  axis-p3245  applied (smb_ip, smb_creds, motion)
192.168.1.102  axis-p3245  applied (smb_ip, smb_creds, motion)
192.168.1.103  axis-m3106  applied (smb_ip, smb_creds, motion)
192.168.1.104  axis-m3106  applied (smb_ip, smb_creds, motion)
```

Alex pushes `cameras.yaml` to the home lab git repo. The camera fleet is now infrastructure.

**Capabilities revealed:** subnet discovery, VAPIX apply for all three settings, per-camera success output, YAML parsing.

---

### Journey 2: Drift Correction After NAS IP Change

Six months later, Alex migrates the NAS to a new IP. One line changes in `cameras.yaml`. Alex runs `cctv apply cameras.yaml`.

```
192.168.1.101  axis-p3245  applied (smb_ip)
192.168.1.102  axis-p3245  no change
192.168.1.103  axis-m3106  applied (smb_ip)
192.168.1.104  axis-m3106  applied (smb_ip)
```

Camera 102 had already been manually updated as a test — cctv detects it's already at desired state and skips it. The other three converge in seconds. Alex commits the one-line diff to git. This is the "aha moment."

**Capabilities revealed:** idempotency / read-before-write, per-setting change granularity, "no change" signal distinct from "applied."

---

### Journey 3: Partial Failure — Camera Offline

Alex runs `cctv apply` while one camera is temporarily offline.

```
192.168.1.101  axis-p3245  applied (smb_ip, smb_creds, motion)
192.168.1.102  axis-p3245  applied (smb_ip, smb_creds, motion)
192.168.1.103  axis-m3106  FAILED — unreachable (connection timeout)
192.168.1.104  axis-m3106  applied (smb_ip, smb_creds, motion)

1 camera failed. Re-run apply when 192.168.1.103 is back online.
```

The run doesn't abort. Three cameras are configured. When the offline camera comes back up, `cctv apply` converges it without re-applying to the already-configured cameras.

**Capabilities revealed:** failure isolation (no abort-on-error), actionable error messages, idempotency enabling safe re-runs.

---

### Journey 4: Discovery-Only Before Apply

Alex is unsure whether all cameras are reachable after a network change. Before running apply, Alex runs `cctv list`:

```
Scanning 192.168.1.0/24...
Found 4 Axis cameras:
  192.168.1.101  axis-p3245  (reachable)
  192.168.1.102  axis-p3245  (reachable)
  192.168.1.103  axis-m3106  (reachable)
  192.168.1.104  axis-m3106  (reachable)
```

Confident all four are up, Alex proceeds with `cctv apply`. No changes were made during `list`.

**Capabilities revealed:** read-only discovery mode, subnet scan output format, clear separation of list vs. apply.

---

### Journey Requirements Summary

| Capability | Revealed By |
|---|---|
| Subnet discovery (read-only) | Journeys 1, 4 |
| YAML config parsing | Journeys 1, 2 |
| VAPIX apply: SMB IP, SMB creds, motion detection | Journey 1 |
| Read-before-write / idempotency | Journeys 2, 3 |
| Per-camera, per-setting output (applied / no-change / failed) | Journeys 1, 2, 3 |
| Failure isolation — continue on error | Journey 3 |
| Actionable error messages | Journey 3 |
| Clear "no change" signal (not silence) | Journey 2 |

## Innovation & Competitive Analysis

### Innovation Pattern

**Mental model transfer:** cctv applies the desired-state / eventually-consistent model — established in Ansible, Terraform, and Kubernetes — to IP camera configuration. The result is a new user experience for home sysadmins: cameras converging toward declared state rather than receiving one-time imperative commands.

**Market position:** No open-source CLI exists for Axis camera configuration. AXIS Device Manager is GUI-only and Windows-only. cctv occupies an uncontested niche.

### Competitive Landscape

| Tool | Scriptable | Declarative config | Auto-discovery | Open source |
|---|---|---|---|---|
| AXIS Device Manager | No | No | Yes | No |
| Manual web UI | No | No | No | — |
| Home Assistant (Axis) | Partial | No | Partial | Yes |
| **cctv** | **Yes** | **Yes** | **Yes** | **Yes** |

## CLI Tool Requirements

### Command Structure

```
cctv list [--subnet <CIDR>]
cctv apply <config.yaml> [--subnet <CIDR>]
cctv status <config.yaml> [--subnet <CIDR>] [--json]
```

- `list` — discovery only, read-only, no side effects
- `apply` — convergence operation; reads config, discovers cameras, applies settings
- `status` — read-only fleet status report; reads config, discovers cameras, reports each camera's live VAPIX state (motion detection, action rules, SMB share, time, retention) without applying any changes
- `--subnet` — overrides the subnet defined in config file
- `--json` (status only) — machine-readable JSON output instead of human-readable text

### Output Format

Per-camera lines with status (`applied`, `no change`, `FAILED`) and error detail on failure. Summary line at end.

```
192.168.1.101  axis-p3245  applied (smb_ip, smb_creds, motion)
192.168.1.102  axis-p3245  no change
192.168.1.103  axis-m3106  FAILED — unreachable (connection timeout)

Summary: 2 applied, 1 no change, 1 failed
```

Machine-readable output (`--output json`) for `apply`/`list` remains a Phase 2 feature. `cctv status --json` (Epic 4) is scoped narrower: JSON output for the read-only status report only.

`cctv status` per-camera text block:

```
192.168.1.101  AXIS M3005 Network Camera
  motion app:   VideoMotionDetection (AXIS Video Motion Detection) — Running
  motion:       enabled, sensitivity 90, full-frame window
  action rules: cctv_motion_record — motion → record to NetworkShare (pre 5s, post 2s)
  smb share:    192.168.1.100:/cctv  (user: cctv)
  time:         MSK-3
  retention:    33 days
```

### Exit Codes

- `0` — all cameras succeeded (applied or no-change)
- `1` — one or more cameras failed
- `2` — fatal error (config parse failure, no cameras found, invalid subnet)

### Config Schema

```yaml
subnet: 192.168.1.0/24

credentials:
  username: root
  password: plaintext  # documented plaintext trade-off

timeout: 5

# Fleet-wide — applied to every discovered camera regardless of which
# profile it matches. Each is independently optional: omit any one to
# leave that setting untouched on every camera.
ntp_fallback_servers: [pool.ntp.org, ntp1.vniiftri.ru]
timezone: CET-1CEST,M3.5.0,M10.5.0/3
recording_retention_days: 33   # 0 = unlimited

profiles:
  - name: legacy-smb
    match:
      models: [M3005, P1204, M2014-E]
    target_firmware: "5.51.7.4"   # precondition only; omit/null to skip the check

    applications:
      video_motion_detection:
        app_package_path: /path/to/AXIS_Video_Motion_Detection_2_2_1.eap  # only if not pre-installed

    motion_detection:
      enabled: true
      sensitivity: 90
      pre_trigger_time: 5
      post_trigger_time: 5

    storage:
      backend: smb
      smb:
        ip: 192.168.1.10
        share: /mnt/cctv
        username: smbuser
        password: smbpass

  - name: m3085v-sd-s3sync
    match:
      models: [M3085-V]
    target_firmware: "12.11.72"

    applications:
      sd_to_s3_sync:
        app_package_path: /path/to/signed_SD_to_S3_Sync_0_9_5_aarch64.eap

    motion_detection:
      enabled: true
      size_percentage: [5, 5]
      time_short_lived_limit: 1
      distance_swaying_object: 5
      pre_trigger_time: 5
      post_trigger_time: 2

    storage:
      backend: sd_s3sync
      sd_s3sync:
        endpoint: https://s3.example-provider.com
        region: us-east-1
        bucket: my-cctv-bucket
        access_key: REPLACE_ME
        secret_key: REPLACE_ME
```

A camera is routed to the **first** profile whose `match.models` contains a
substring of its reported model name. `storage.backend` selects which
same-named nested block (`storage.smb` / `storage.sd_s3sync`) is read; the
two are mutually exclusive and structurally symmetric — both hold *where the
video goes*, while `applications` holds only what's needed to install/run
the app itself (nothing app-specific belongs in `storage`, and nothing
storage-destination-specific belongs in `applications`).

- Python packaging: installable via `pip install cctv` with `cctv` entry point
- Dependencies: `requests`, `pyyaml`, `ipaddress`
- VAPIX authentication: HTTP Digest Auth

## Functional Requirements

### Camera Discovery

- **FR1:** The operator can trigger a scan of a configured IP subnet to discover all reachable Axis cameras.
- **FR2:** The operator can view a list of discovered cameras showing IP address and camera model without making any configuration changes.
- **FR3:** The operator can override the default subnet at runtime without modifying the config file.
- **FR4:** The system can identify Axis cameras on a subnet by probing each IP in the configured CIDR range via HTTP.
- **FR5:** The operator can discover cameras independently of applying configuration (read-only operation).

### Configuration Management

- **FR6:** The operator can define desired camera state in a YAML configuration file.
- **FR7:** The operator can specify camera login credentials (username, password) in the config file.
- **FR8:** The operator can specify SMB share settings (IP, share path, SMB username, SMB password) in the config file. *(Superseded in shape by FR41: these now live under a profile's `storage.smb` block rather than a single top-level `smb` section, so a fleet spanning camera generations can declare more than one destination.)*
- **FR9:** The operator can specify motion detection settings in the config file. *(Superseded in shape by FR43: the settings are declared per profile, and their shape depends on the profile's motion-detection method — a single `sensitivity` value for the legacy `root.Motion` group, or the VMD4 filter set. There is no one motion schema shared across camera generations.)*
- **FR10:** The operator can specify the target subnet in the config file.
- **FR11:** The system can validate the config file structure and report specific parse errors before attempting any camera operations.

### State Convergence

- **FR12:** The operator can apply a config file to all discovered cameras in a single command.
- **FR13:** The system can read the current value of each managed setting from a camera before deciding whether to apply a change.
- **FR14:** The system can skip applying a setting to a camera when the current value already matches the desired state.
- **FR15:** The system can apply configuration changes to multiple cameras in sequence without aborting when one camera fails.
- **FR16:** The system can apply the same config file multiple times and produce the same end state with no errors on subsequent runs (idempotency).

### SMB Share Configuration

- **FR17:** The system can configure the SMB share IP address on an Axis camera via the VAPIX API.
- **FR18:** The system can configure the SMB share path and credentials on an Axis camera via the VAPIX API.

### Motion Detection Configuration

- **FR19:** The system can enable or disable built-in motion detection on an Axis camera via the VAPIX API.
- **FR20:** The system can configure motion detection sensitivity on an Axis camera via the VAPIX API. *(Legacy generation only — the `root.Motion` group exposes a single 0–100 sensitivity knob. The VMD4 generation has no equivalent scalar; see FR43.)*

### Observability & Reporting

- **FR21:** The operator can see per-camera outcome after an apply run: one of `applied`, `no change`, or `FAILED` for each discovered camera.
- **FR22:** The operator can see which specific settings were applied or skipped for each camera in the apply output.
- **FR23:** The operator can see a summary line at the end of an apply run with counts of applied, no-change, and failed cameras.
- **FR24:** The operator can see an actionable error message when a camera fails, including the camera IP and the reason for failure.
- **FR25:** The system can exit with code `0` when all cameras succeed (applied or no-change), `1` when one or more cameras fail, and `2` on a fatal error.
- **FR26:** The system can write all error and diagnostic output to stderr, keeping stdout clean for status output.
- **FR27:** The operator can see the count of cameras found during a `cctv list` run along with their IPs and models.
- **FR28:** The system can detect whether the AXIS Video Motion Detection app is installed and running on a camera, and — for legacy cameras where it doesn't ship pre-installed — install it from a local `.eap` package path specified in config before configuring motion detection.
- **FR35:** The system can link the motion-detection action rule to the actual motion source in use on a camera — the installed AXIS Video Motion Detection app's own event topic on legacy cameras where that app had to be installed (FR28), rather than assuming the fixed built-in window-based motion topic applies to every camera.

### Camera Profiles (added 2026-09-02)

- **FR36:** The operator can define multiple named profiles in the config file, each matching one or more camera models.
- **FR37:** The system can match a discovered camera to the first profile whose configured models list matches the camera's reported model string.
- **FR38:** The system can report a camera as failed, distinctly from a VAPIX error, when it matches no configured profile.
- **FR39:** The operator can pin a `target_firmware` version per profile; the system checks the camera's actual firmware against it before applying any other setting, and fails that camera (applying nothing) on a mismatch.
- **FR40:** The system never upgrades or otherwise modifies camera firmware — `target_firmware` is a read-only precondition, not a convergence target.
- **FR41:** The operator can select a storage backend per profile (`smb` or `sd_s3sync`), each with its own destination settings (SMB share IP/path/credentials, or S3 endpoint/region/bucket/credentials).
- **FR42:** The system can install and configure the `sd_to_s3_sync` ACAP from a local package path, and — because the app reads its configuration only at process startup, never hot-reloading — must write configuration *before* first starting it, and restart an already-running app whenever its configuration changed. A running app whose configuration did not change is left alone, so a reconcile never interrupts an in-flight upload.
- **FR43:** The system can configure the built-in VMD4 motion-detection engine (filter-based: minimum object size, short-lived-object time limit, swaying-object distance) as an alternative to the legacy sensitivity-based `root.Motion` group, selected implicitly by which profile a camera matches.
- **FR44:** The operator can define fleet-wide settings (NTP fallback servers, timezone, recording retention) once in the config file, applied identically to every discovered camera regardless of which profile it matches.
- **FR45:** The system can configure recording retention against the correct underlying storage group (SD card vs. network share) depending on the matched profile's storage backend, from a single fleet-wide `recording_retention_days` value.

### Motion Recording Pipeline (added 2026-09-03)

These requirements describe the link that makes a configured camera actually
record: a motion event has to be bound to a recording action, or every other
setting in the profile is inert. Both backends need this binding; they differ
only in event source and recording destination.

- **FR46:** The system can ensure a motion→record action rule exists on each camera, binding the profile's motion event source to a recording action targeting that profile's storage: the legacy or built-in motion topic recording to `NetworkShare` on the `smb` backend, and the VMD4 profile topic recording to `SD_DISK` on the `sd_s3sync` backend. Pre/post-event durations come from the profile's motion settings.
- **FR47:** The system can bind the `sd_s3sync` recording rule to the camera's actual VMD4 profile identifier rather than the "any profile" wildcard, because the VAPIX rule-creation API accepts the concrete topic but rejects the wildcard form (which nonetheless appears when reading back rules created by other means).
- **FR48:** The system can converge an existing action rule that is present but incorrect — wrong event topic, wrong storage target, or wrong durations — by removing and recreating it, since the underlying API offers no in-place edit of an action configuration. A rule that is already correct is left untouched, and a disabled rule does not count as satisfying the requirement.
- **FR49:** The system can expand the built-in VMD4 detection profile's trigger area to cover the full frame, because the factory-default profile covers only part of it and motion outside that area never raises an event. Existing filter settings, profile identifiers, and other trigger types are preserved.

### Camera Identity and Storage Namespacing (added 2026-09-03)

- **FR50:** The system can synchronise a camera's DHCP-assigned hostname onto its configured static hostname when the two differ, because the hostname determines each camera's own namespace within shared storage — the SMB subfolder on the `smb` backend, and the S3 key prefix on the `sd_s3sync` backend. A camera with no DHCP-assigned hostname is left unchanged.
- **FR51:** The system deliberately does not manage the sync ACAP's S3 key prefix. The ACAP derives it from the camera's own hostname at runtime (FR50), which gives every camera a distinct prefix in a shared bucket with no per-camera configuration — so the fleet-wide config stays genuinely fleet-wide, and adding a camera needs no new config entry.

### Fleet Status Reporting

- **FR29:** The operator can run `cctv status <config.yaml>` to see the current live VAPIX state of each discovered camera without applying any changes.
- **FR30:** The system can report each camera's motion detection app installation/running status and its configured window(s)/sensitivity.
- **FR31:** The system can report each camera's configured action rules (events) together with their linked action configuration (trigger condition, target action, pre/post duration).
- **FR32:** The system can report each camera's configured SMB/network share settings (IP, share path, username) excluding passwords.
- **FR33:** The system can report each camera's current timezone and recording retention (cleanup max age) setting.
- **FR34:** The operator can request `cctv status` output as JSON via a `--json` flag for machine-readable consumption.

## Non-Functional Requirements

### Performance

- `cctv list` on a /24 subnet completes within 30 seconds under normal network conditions.
- `cctv apply` completes within 60 seconds for a fleet of up to 10 cameras under normal network conditions.
- Per-camera connection timeout is configurable (default: 5 seconds) to prevent a single unreachable host from blocking the entire run.
- Camera probing during discovery is parallelised or time-bounded to avoid O(n) sequential blocking on large subnets.

### Security

- Camera credentials, SMB credentials, and S3 access/secret keys are stored in plaintext in the config YAML — explicit documented trade-off for v1. The config file is gitignored for this reason; any file holding values pulled off a live camera (e.g. a captured `root.Sds3sync.*` dump) must follow the same rule and never be tracked.
- Whether every camera should share one S3 access key or receive its own scoped credentials is an open deployment decision, not a tool constraint — cctv applies whatever the profile declares. Least-privilege per-camera keys are preferable once a fleet grows beyond a handful of units.
- The README warns that the config file contains plaintext credentials and advises against committing it to public repositories.
- Credentials never appear in stdout/stderr output.
- All VAPIX API communication uses HTTP Digest Authentication as provided by the Axis camera.
- The tool does not store credentials beyond the lifetime of a single run (no credential caching, no keychain integration).

### Reliability

- A connection failure to one camera does not affect configuration of remaining cameras in the same run.
- A camera that does not respond within the configured timeout is marked `FAILED`, not left hanging.
- The tool exits with a documented, non-zero exit code on any failure condition, enabling reliable use in shell scripts.
- VAPIX API errors (non-2xx responses) are captured and surfaced as actionable error messages, not silently ignored.
