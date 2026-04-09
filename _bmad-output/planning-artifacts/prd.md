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

## Executive Summary

**cctv** is a Python CLI tool that brings infrastructure-as-code to Axis IP camera fleets. Home sysadmins define desired camera state once in a YAML file; `cctv apply` discovers all Axis cameras on the local subnet and converges each one to that state via the VAPIX API. The tool manages exactly three concerns: SMB share IP, SMB credentials, and motion detection settings — the configuration surface that matters for a home security setup.

The target user is a technically proficient home sysadmin who already operates their network as infrastructure — running Ansible playbooks, Docker Compose stacks, and self-hosted services — but has no declarative option for their cameras. Every configuration change today means clicking through each camera's web UI manually, with no audit trail and inevitable drift. cctv eliminates that entirely.

### What Makes This Special

The core differentiator is the **eventually consistent model**. cctv does not push config once and forget — it declares desired state and converges cameras toward it every time it runs. The same command that configures cameras on day one also corrects drift on day 100. The YAML config file is the artifact: version-controllable, diffable, and reviewable. This is the mental model home sysadmins already use for every other part of their infrastructure; cctv extends it to cameras.

Deliberate opinionation is a feature, not a limitation. By targeting only the three settings that matter for home use (SMB IP, SMB credentials, motion detection), the config schema stays minimal and the tool stays focused. It is not a generic VAPIX wrapper.

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
- `cctv apply <config.yaml>` — parse YAML config, discover cameras, converge each to desired state
- Settings managed: SMB share IP, SMB credentials, motion detection parameters (exactly these three)
- Read-before-write idempotency: check current state before applying, skip if already correct
- Failure isolation: continue applying to remaining cameras if one fails
- Per-camera output: `applied` / `no change` / `FAILED` with error detail and summary line
- Exit codes: 0 (all ok), 1 (partial failure), 2 (fatal error)
- YAML config with plaintext credentials (trade-off documented in README)

### Post-MVP Features (Phase 2)

- `--dry-run` — show what would change without applying
- `--diff` — compare live camera state against config
- `--output json` for scripting and log parsing
- Expanded VAPIX settings: network config, hostname, additional motion parameters
- Shell completion

### Vision (Phase 3)

- Multi-vendor support: ONVIF-compliant cameras, Hikvision, Dahua
- Ansible module wrapper
- Full VAPIX API surface coverage

### Risk Mitigation

**Technical:** VAPIX API behaviour varies across Axis firmware versions. Test against real hardware before MVP is considered complete. No mocking of VAPIX responses in integration tests.

**Scope:** The three-setting constraint is the guardrail — any setting outside `{smb_ip, smb_creds, motion_detection}` is post-MVP regardless of VAPIX capability.

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
```

- `list` — discovery only, read-only, no side effects
- `apply` — convergence operation; reads config, discovers cameras, applies settings
- `--subnet` — overrides the subnet defined in config file

### Output Format

Per-camera lines with status (`applied`, `no change`, `FAILED`) and error detail on failure. Summary line at end.

```
192.168.1.101  axis-p3245  applied (smb_ip, smb_creds, motion)
192.168.1.102  axis-p3245  no change
192.168.1.103  axis-m3106  FAILED — unreachable (connection timeout)

Summary: 2 applied, 1 no change, 1 failed
```

Machine-readable output (`--output json`) is a Phase 2 feature.

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
smb:
  ip: 192.168.1.10
  share: /mnt/cctv
  username: smbuser
  password: smbpass
motion_detection:
  enabled: true
  sensitivity: 50
```

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
- **FR8:** The operator can specify SMB share settings (IP, share path, SMB username, SMB password) in the config file.
- **FR9:** The operator can specify motion detection settings (enabled/disabled, sensitivity) in the config file.
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
- **FR20:** The system can configure motion detection sensitivity on an Axis camera via the VAPIX API.

### Observability & Reporting

- **FR21:** The operator can see per-camera outcome after an apply run: one of `applied`, `no change`, or `FAILED` for each discovered camera.
- **FR22:** The operator can see which specific settings were applied or skipped for each camera in the apply output.
- **FR23:** The operator can see a summary line at the end of an apply run with counts of applied, no-change, and failed cameras.
- **FR24:** The operator can see an actionable error message when a camera fails, including the camera IP and the reason for failure.
- **FR25:** The system can exit with code `0` when all cameras succeed (applied or no-change), `1` when one or more cameras fail, and `2` on a fatal error.
- **FR26:** The system can write all error and diagnostic output to stderr, keeping stdout clean for status output.
- **FR27:** The operator can see the count of cameras found during a `cctv list` run along with their IPs and models.

## Non-Functional Requirements

### Performance

- `cctv list` on a /24 subnet completes within 30 seconds under normal network conditions.
- `cctv apply` completes within 60 seconds for a fleet of up to 10 cameras under normal network conditions.
- Per-camera connection timeout is configurable (default: 5 seconds) to prevent a single unreachable host from blocking the entire run.
- Camera probing during discovery is parallelised or time-bounded to avoid O(n) sequential blocking on large subnets.

### Security

- Camera credentials and SMB credentials are stored in plaintext in the config YAML — explicit documented trade-off for v1.
- The README warns that the config file contains plaintext credentials and advises against committing it to public repositories.
- Credentials never appear in stdout/stderr output.
- All VAPIX API communication uses HTTP Digest Authentication as provided by the Axis camera.
- The tool does not store credentials beyond the lifetime of a single run (no credential caching, no keychain integration).

### Reliability

- A connection failure to one camera does not affect configuration of remaining cameras in the same run.
- A camera that does not respond within the configured timeout is marked `FAILED`, not left hanging.
- The tool exits with a documented, non-zero exit code on any failure condition, enabling reliable use in shell scripts.
- VAPIX API errors (non-2xx responses) are captured and surfaced as actionable error messages, not silently ignored.
