# Story 1.2: YAML Config File Loading

Status: done

## Story

As a home sysadmin,
I want to define my camera fleet's desired state in a `cameras.yaml` file,
so that I have a single, version-controllable source of truth for all camera settings.

## Acceptance Criteria

1. **Given** a valid `cameras.yaml` with all required keys (`subnet`, `credentials`, `smb`, `motion_detection`), **when** `config.py` parses it, **then** a `CameraConfig` dataclass is returned with all fields correctly populated, **and** the `timeout` field defaults to `5` if not specified in the YAML.

2. **Given** `cameras.yaml.example` is present in the repository (created in Story 1.1), **when** I review its contents, **then** all config keys are documented with example values, **and** the `.gitignore` excludes `cameras.yaml` to protect plaintext credentials. *(Both already satisfied by Story 1.1 — verify, do not recreate.)*

## Tasks / Subtasks

- [x] Create `src/cctv/config.py` with `ConfigError`, `CameraConfig` dataclass, and `load_config()` function (AC: 1)
  - [x] Define `class ConfigError(Exception)` — placeholder for Story 1.3 validation; defined here because Story 1.3 imports it from `config.py`
  - [x] Define `CameraConfig` dataclass with all fields (see exact field names in Dev Notes)
  - [x] Implement `load_config(path: Path) -> CameraConfig` — reads file, calls `yaml.safe_load()`, maps nested YAML keys to flat dataclass fields
  - [x] `timeout` must default to `5` when key is absent from YAML (`data.get("timeout", 5)`)
  - [x] No `import requests`, no `print()` anywhere in this file
- [x] Update `tests/conftest.py` with a shared `camera_config` fixture (AC: 1)
  - [x] `@pytest.fixture` returning a `CameraConfig` with all fields populated (see example in Dev Notes)
  - [x] Import `CameraConfig` from `cctv.config`
- [x] Create `tests/test_config.py` with unit tests (AC: 1)
  - [x] `test_load_valid_config` — write a tmp YAML with all keys → assert all fields match
  - [x] `test_timeout_defaults_to_5` — write a tmp YAML without `timeout` key → assert `config.timeout == 5`
  - [x] `test_load_config_explicit_timeout` — write a tmp YAML with `timeout: 10` → assert `config.timeout == 10`
- [x] Verify `cameras.yaml.example` contains all keys and `.gitignore` excludes `cameras.yaml` (AC: 2) — read-only check, no changes expected
- [x] Run `pytest` — all tests pass (AC: 1)

### Review Findings

- [x] [Review][Patch] Credentials leak in `CameraConfig.__repr__` — `password` and `smb_password` appear in repr output [src/cctv/config.py:17,22]
- [x] [Review][Defer] `load_config` raises bare `KeyError`/`FileNotFoundError` instead of `ConfigError` — deferred, pre-existing; scope is Story 1.3 config validation
- [x] [Review][Defer] `bool('false') == True` edge case for YAML string instead of boolean — deferred, pre-existing; type validation is Story 1.3
- [x] [Review][Defer] `timeout: null` → `int(None)` TypeError — deferred, pre-existing; scope is Story 1.3
- [x] [Review][Defer] `yaml.safe_load` returns `None` for empty file — deferred, pre-existing; scope is Story 1.3

## Dev Notes

### Files to Create

- `src/cctv/config.py` — **new file**
- `tests/test_config.py` — **new file**

### Files to Modify

- `tests/conftest.py` — add `camera_config` fixture (currently a placeholder comment)

### Files to Verify (Read-Only)

- `cameras.yaml.example` — verify all keys present (created in Story 1.1)
- `.gitignore` — verify `cameras.yaml` excluded (done in Story 1.1)

### Module Boundary Rules (Architecture-Enforced)

- `config.py` — **NO** `import requests`. **NO** `print()`. No network calls.
- `src/cctv/__init__.py` — remains **EMPTY**. Do not add imports.

### `CameraConfig` Exact Field Names and Types

These field names are used by `reconciler.py` (Story 3.1) and `executor.py` — do not change them:

```python
from dataclasses import dataclass

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

### YAML-to-Dataclass Mapping

The config YAML is nested; `CameraConfig` is flat. `load_config` must do this mapping:

| YAML path | CameraConfig field |
|-----------|-------------------|
| `subnet` | `subnet` |
| `credentials.username` | `username` |
| `credentials.password` | `password` |
| `smb.ip` | `smb_ip` |
| `smb.share` | `smb_share` |
| `smb.username` | `smb_username` |
| `smb.password` | `smb_password` |
| `motion_detection.enabled` | `motion_enabled` |
| `motion_detection.sensitivity` | `motion_sensitivity` |
| `timeout` (optional, default 5) | `timeout` |

### `config.py` Implementation Pattern

```python
from __future__ import annotations

import yaml
from dataclasses import dataclass
from pathlib import Path


class ConfigError(Exception):
    """Config file missing, unreadable, or schema invalid."""


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


def load_config(path: Path) -> CameraConfig:
    with path.open() as f:
        data = yaml.safe_load(f)
    creds = data["credentials"]
    smb = data["smb"]
    motion = data["motion_detection"]
    return CameraConfig(
        subnet=data["subnet"],
        username=creds["username"],
        password=creds["password"],
        smb_ip=smb["ip"],
        smb_share=smb["share"],
        smb_username=smb["username"],
        smb_password=smb["password"],
        motion_enabled=bool(motion["enabled"]),
        motion_sensitivity=int(motion["sensitivity"]),
        timeout=int(data.get("timeout", 5)),
    )
```

**Note:** Do NOT add validation (missing key checks, CIDR validation, etc.) — that is Story 1.3. Story 1.2 only handles valid configs. If a key is missing, a native `KeyError` is acceptable here.

### `conftest.py` Fixture Pattern

```python
import pytest
from cctv.config import CameraConfig


@pytest.fixture
def camera_config() -> CameraConfig:
    return CameraConfig(
        subnet="192.168.1.0/24",
        username="root",
        password="testpass",
        smb_ip="192.168.1.10",
        smb_share="/mnt/cctv",
        smb_username="smbuser",
        smb_password="smbpass",
        motion_enabled=True,
        motion_sensitivity=50,
        timeout=5,
    )
```

### `test_config.py` Pattern — Use `tmp_path` Fixture

```python
from pathlib import Path
from cctv.config import load_config, CameraConfig

VALID_YAML = """
subnet: 192.168.1.0/24
credentials:
  username: root
  password: testpass
smb:
  ip: 192.168.1.10
  share: /mnt/cctv
  username: smbuser
  password: smbpass
motion_detection:
  enabled: true
  sensitivity: 50
timeout: 5
"""

def test_load_valid_config(tmp_path):
    config_file = tmp_path / "cameras.yaml"
    config_file.write_text(VALID_YAML)
    cfg = load_config(config_file)
    assert cfg.subnet == "192.168.1.0/24"
    assert cfg.username == "root"
    assert cfg.smb_ip == "192.168.1.10"
    assert cfg.smb_share == "/mnt/cctv"
    assert cfg.motion_enabled is True
    assert cfg.motion_sensitivity == 50
    assert cfg.timeout == 5
```

### Previous Story Learnings (from Story 1.1)

- **`pytest testpaths = ["tests"]`** already in `pyproject.toml` — no change needed.
- **`build-backend = "setuptools.build_meta"`** already fixed.
- **`list` command renamed to `list_cameras`** with `@app.command(name="list")` — confirmed in review.
- **Module boundary violation caught in review:** The code review flagged `list` shadowing built-in — be careful with naming in new modules.
- **venv path:** `.venv/Scripts/python -m pytest` to run tests in the correct environment.
- Test file `tests/test_cli.py` already exists with 3 passing tests — do NOT touch it.

### Architecture Constraints

- `ConfigError` is defined in `config.py` and later imported by `cli.py` (Story 1.3) for catching at the entry point. Define it now even though validation logic is Story 1.3.
- `CameraConfig` is used by `scanner.py` (Story 2.1), `executor.py` (Story 3.4), and `reconciler.py` (Story 3.1) — field names are a shared contract.
- Future stories will add: `mock HTTPDigestAuth` and `mock requests.get/post` to `conftest.py`. Leave placeholder comments for those.

### References

- [Source: architecture.md#Core Architectural Decisions] — CameraConfig dataclass definition
- [Source: architecture.md#Error Handling Patterns] — ConfigError definition
- [Source: architecture.md#Implementation Patterns] — Module boundary rules
- [Source: architecture.md#Project Structure & Boundaries] — conftest.py fixtures responsibility
- [Source: epics.md#Story 1.2] — Acceptance criteria and story statement
- [Source: prd.md#Config Schema] — YAML structure reference

## Dev Agent Record

### Agent Model Used

claude-sonnet-4-6

### Debug Log References

- No issues encountered. All 5 tasks completed without errors.

### Completion Notes List

- `src/cctv/config.py` created: `ConfigError`, `CameraConfig` dataclass (9 fields + timeout default), `load_config()` with nested YAML → flat dataclass mapping
- `tests/conftest.py` updated: added `camera_config` fixture with `@pytest.fixture`, placeholder TODOs for Story 1.4 mock fixtures
- `tests/test_config.py` created: 3 tests using `tmp_path` — valid load, timeout default, explicit timeout
- AC2 verified: `cameras.yaml.example` has all keys, `.gitignore` excludes `cameras.yaml` (both from Story 1.1)
- 6 pytest tests pass (3 existing CLI tests + 3 new config tests), 0 failures

### File List

- src/cctv/config.py
- tests/conftest.py
- tests/test_config.py
