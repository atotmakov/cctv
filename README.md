# cctv

Infrastructure-as-code for Axis IP camera fleets. Define desired camera state once in a YAML file; `cctv apply` discovers all Axis cameras on the local subnet and converges each one to that state via the VAPIX API.

## Install

```bash
pip install cctv-as-code
```

For local development:

```bash
git clone https://github.com/atotmakov/cctv.git
cd cctv
pip install -e ".[dev]"
```

Requires Python 3.11+.

## Usage

```bash
# Discover all Axis cameras on the configured subnet (read-only)
cctv list

# Override subnet at runtime
cctv list --subnet 10.0.0.0/24

# Apply config to all discovered cameras
cctv apply cameras.yaml

# Override subnet at runtime
cctv apply cameras.yaml --subnet 10.0.0.0/24
```

## Config

Copy `cameras.yaml.example` to `cameras.yaml` and fill in your values:

```yaml
subnet: 192.168.1.0/24

credentials:
  username: root
  password: changeme

smb:
  ip: 192.168.1.10
  share: cctv
  username: smbuser
  password: smbpass

motion_detection:
  enabled: true
  sensitivity: 90
  pre_trigger_time: 5   # seconds to record before motion event (default: 5)
  post_trigger_time: 5  # seconds to record after motion event (default: 5)

recording_retention_days: 33

timezone: CET-1CEST,M3.5.0,M10.5.0/3  # POSIX timezone string

timeout: 5
```

> ⚠️ **Security warning:** `cameras.yaml` contains plaintext credentials. Do not commit it to public repositories. It is excluded from git by `.gitignore`.

## Managed settings

| Setting | Description |
|---|---|
| `smb.ip` | IP address of the SMB server |
| `smb.share` | Share name cameras write recordings to |
| `smb.username` / `smb.password` | SMB credentials |
| `motion_detection.enabled` | Enable or disable motion detection |
| `motion_detection.sensitivity` | Motion sensitivity 0–100 |
| `motion_detection.pre_trigger_time` | Seconds to record before motion event (default: 5) |
| `motion_detection.post_trigger_time` | Seconds to record after motion event (default: 5) |
| `recording_retention_days` | Days to keep recordings on the share (default: 33) |
| `timezone` | POSIX timezone string — cameras use this as the SMB folder timestamp and display time. NTP server is obtained from DHCP. Omit to leave unchanged. |

### SMB folder naming

Each camera uses its network hostname as the subfolder name inside the share (e.g. `\\server\cctv\front-door\`). If a DHCP hostname is assigned to the camera, `cctv apply` automatically copies it to the static hostname so the folder name is human-readable instead of the default MAC-based name (e.g. `axis-00408ce2767e`).

### Timezone

Set `timezone` as a POSIX timezone string. Examples:

| Location | String |
|---|---|
| UTC | `UTC0` |
| Central European (CET/CEST) | `CET-1CEST,M3.5.0,M10.5.0/3` |
| Eastern European (EET/EEST) | `EET-2EEST,M3.5.0/3,M10.5.0/4` |
| Moscow (MSK, no DST) | `MSK-3` |

NTP is obtained automatically from DHCP (option 42). Static NTP server configuration is not managed by this tool.

## Exit codes

| Code | Meaning |
|------|---------|
| 0 | All cameras succeeded (applied or no change) |
| 1 | One or more cameras failed |
| 2 | Fatal error (config invalid, no cameras found) |

## Run tests

```bash
pytest
```
