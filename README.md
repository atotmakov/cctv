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
  share: /mnt/cctv
  username: smbuser
  password: smbpass
motion_detection:
  enabled: true
  sensitivity: 50
timeout: 5
```

> ⚠️ **Security warning:** `cameras.yaml` contains plaintext credentials. Do not commit it to public repositories. It is excluded from git by `.gitignore`.

## Exit codes

| Code | Meaning |
|------|---------|
| 0 | All cameras succeeded (applied or no change) |
| 1 | One or more cameras failed |
| 2 | Fatal error (config invalid, no cameras found) |

## Managed settings

- SMB share IP, path, and credentials
- Motion detection enabled/disabled and sensitivity

## Run tests

```bash
pytest
```
