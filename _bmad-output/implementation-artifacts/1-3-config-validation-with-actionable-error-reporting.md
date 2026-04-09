# Story 1.3: Config Validation with Actionable Error Reporting

Status: done

## Story

As a home sysadmin,
I want clear, specific error messages when my config file is missing or malformed,
so that I can fix it immediately without debugging the tool.

## Acceptance Criteria

1. **Given** a config file missing a required key (e.g. `smb.ip`), **when** `cctv` attempts to load it, **then** a `ConfigError` is raised with a message naming the specific missing key, **and** the process exits with code 2 before attempting any camera operations.

2. **Given** the config file path does not exist, **when** I run `cctv apply nonexistent.yaml`, **then** an error message is printed to stderr stating the file was not found, **and** the process exits with code 2.

3. **Given** a config file with an invalid subnet value (not a valid CIDR), **when** `cctv` attempts to load it, **then** a `ConfigError` is raised identifying the invalid value, **and** the process exits with code 2.

## Tasks / Subtasks

- [x] Harden `src/cctv/config.py` — add validation to `load_config()` (AC: 1, 2, 3)
  - [x] Catch `FileNotFoundError` / `PermissionError` from `path.open()` → re-raise as `ConfigError(f"Config file not found: {path}")` (AC: 2)
  - [x] Catch `yaml.YAMLError` from `yaml.safe_load()` → re-raise as `ConfigError(f"YAML parse error: {e}")` (AC: 1)
  - [x] Guard against `yaml.safe_load()` returning `None` (empty file) → raise `ConfigError("Config file is empty")` (AC: 1)
  - [x] Catch `KeyError` for missing top-level keys (`subnet`, `credentials`, `smb`, `motion_detection`) → re-raise as `ConfigError(f"Missing required key: {key}")` (AC: 1)
  - [x] Catch `KeyError` for missing nested keys → re-raise as `ConfigError(f"Missing required key: {section}.{key}")` (AC: 1)
  - [x] Validate `subnet` CIDR using `ipaddress.ip_network(data["subnet"], strict=False)` → raise `ConfigError(f"Invalid subnet: '{value}' is not a valid CIDR")` on `ValueError` (AC: 3)
  - [x] Fix `timeout: null` edge case: use `data.get("timeout") or 5` instead of `data.get("timeout", 5)` (guards `int(None)` TypeError) (AC: 1)
  - [x] No `import requests`, no `print()` in this file
- [x] Update `src/cctv/cli.py` — catch `ConfigError`, exit with code 2 (AC: 1, 2, 3)
  - [x] In `apply()`: wrap `load_config(config)` in `try/except ConfigError as e:` → `typer.echo(f"Error: {e}", err=True)` + `raise typer.Exit(code=2)` (AC: 1, 2, 3)
  - [x] Update `config` argument: `typer.Argument(..., exists=True, file_okay=True, dir_okay=False, readable=True, ...)` so Typer validates path existence before the command body runs (AC: 2)
  - [x] Add `--subnet` CIDR validation callback: if `--subnet` is provided, validate with `ipaddress.ip_network(value, strict=False)` → `raise typer.BadParameter(...)` on `ValueError` (deferred item from Story 1.1 review)
  - [x] Import `ConfigError` from `cctv.config` and `ipaddress` from stdlib
  - [x] No `print()` — use `typer.echo(..., err=True)` for stderr output only
- [x] Add error-case tests to `tests/test_config.py` (AC: 1, 2, 3)
  - [x] `test_missing_top_level_key` — YAML missing `smb` section → assert `ConfigError` raised, message contains `"smb"`
  - [x] `test_missing_nested_key` — YAML with `smb` but missing `smb.ip` → assert `ConfigError` raised, message contains `"smb.ip"`
  - [x] `test_file_not_found` — call `load_config(Path("nonexistent.yaml"))` → assert `ConfigError` raised, message contains file path
  - [x] `test_empty_file` — YAML file with empty content → assert `ConfigError` raised
  - [x] `test_invalid_subnet` — YAML with `subnet: not-a-cidr` → assert `ConfigError` raised, message contains `"not-a-cidr"`
  - [x] `test_invalid_yaml_syntax` — file with `{bad: [yaml` → assert `ConfigError` raised
- [x] Add integration tests to `tests/test_cli.py` (AC: 1, 2)
  - [x] `test_apply_missing_config_file` — invoke `apply nonexistent.yaml` → assert `exit_code != 0`
  - [x] `test_apply_invalid_config` — write a YAML missing `smb`, invoke `apply` → assert `exit_code == 2`
- [x] Run `pytest` — all tests pass

## Dev Notes

### Files to Modify

- `src/cctv/config.py` — add validation, fix `timeout` null edge case
- `src/cctv/cli.py` — catch ConfigError, update Path argument, add subnet callback
- `tests/test_config.py` — add error-case tests
- `tests/test_cli.py` — add integration tests for exit code 2

### Module Boundary Rules

- `config.py` — **NO** `import requests`, **NO** `print()`. `ipaddress` stdlib is fine.
- `cli.py` — **NO** `print()`. Use `typer.echo(..., err=True)` for stderr messages only. No business logic — only wiring and error surfacing.
- `src/cctv/__init__.py` — remains **EMPTY**.

### Hardened `load_config()` Implementation Pattern

```python
import ipaddress

def load_config(path: Path) -> CameraConfig:
    try:
        with path.open() as f:
            data = yaml.safe_load(f)
    except FileNotFoundError:
        raise ConfigError(f"Config file not found: {path}")
    except PermissionError:
        raise ConfigError(f"Config file not readable: {path}")
    except yaml.YAMLError as e:
        raise ConfigError(f"YAML parse error: {e}")

    if not isinstance(data, dict):
        raise ConfigError("Config file is empty or not a YAML mapping")

    for key in ("subnet", "credentials", "smb", "motion_detection"):
        if key not in data:
            raise ConfigError(f"Missing required key: {key}")

    try:
        ipaddress.ip_network(data["subnet"], strict=False)
    except ValueError:
        raise ConfigError(f"Invalid subnet: '{data['subnet']}' is not a valid CIDR")

    creds = data["credentials"]
    for key in ("username", "password"):
        if key not in creds:
            raise ConfigError(f"Missing required key: credentials.{key}")

    smb = data["smb"]
    for key in ("ip", "share", "username", "password"):
        if key not in smb:
            raise ConfigError(f"Missing required key: smb.{key}")

    motion = data["motion_detection"]
    for key in ("enabled", "sensitivity"):
        if key not in motion:
            raise ConfigError(f"Missing required key: motion_detection.{key}")

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
        timeout=int(data.get("timeout") or 5),
    )
```

**Key changes from Story 1.2:**
- `data.get("timeout") or 5` instead of `data.get("timeout", 5)` — guards against `timeout: null` returning `None`
- All key access is now guarded; `KeyError` is impossible after validation
- `ipaddress` import for CIDR validation (stdlib, no new dependency)

### `cli.py` Changes Pattern

```python
import ipaddress
import typer
from pathlib import Path
from typing import Optional

from cctv.config import ConfigError, load_config

app = typer.Typer()


def _validate_subnet(value: Optional[str]) -> Optional[str]:
    if value is not None:
        try:
            ipaddress.ip_network(value, strict=False)
        except ValueError:
            raise typer.BadParameter(f"'{value}' is not a valid CIDR notation")
    return value


@app.command(name="list")
def list_cameras(
    subnet: Optional[str] = typer.Option(
        None, "--subnet", help="Override subnet (CIDR)", callback=_validate_subnet
    ),
) -> None:
    """Discover Axis cameras on the subnet."""
    raise NotImplementedError


@app.command()
def apply(
    config: Path = typer.Argument(
        ...,
        exists=True,
        file_okay=True,
        dir_okay=False,
        readable=True,
        help="Path to cameras.yaml config file",
    ),
    subnet: Optional[str] = typer.Option(
        None, "--subnet", help="Override subnet (CIDR)", callback=_validate_subnet
    ),
) -> None:
    """Apply config to all discovered cameras."""
    try:
        load_config(config)
    except ConfigError as e:
        typer.echo(f"Error: {e}", err=True)
        raise typer.Exit(code=2)
    raise NotImplementedError
```

**Important:** `exists=True` on `typer.Argument` makes Typer validate the path *before* the command body runs — AC2 (file not found) is partially handled by Typer's built-in check. `load_config` still guards FileNotFoundError for robustness (e.g., file deleted between CLI check and open).

### Test Patterns

**`test_config.py` error cases:**
```python
import pytest
from pathlib import Path
from cctv.config import ConfigError, load_config

def test_missing_top_level_key(tmp_path):
    f = tmp_path / "c.yaml"
    f.write_text("subnet: 192.168.1.0/24\ncredentials:\n  username: u\n  password: p\nmotion_detection:\n  enabled: true\n  sensitivity: 50\n")
    with pytest.raises(ConfigError, match="smb"):
        load_config(f)

def test_file_not_found():
    with pytest.raises(ConfigError, match="not found"):
        load_config(Path("nonexistent_file_xyz.yaml"))

def test_invalid_subnet(tmp_path):
    f = tmp_path / "c.yaml"
    f.write_text(VALID_YAML.replace("192.168.1.0/24", "not-a-cidr"))
    with pytest.raises(ConfigError, match="not-a-cidr"):
        load_config(f)
```

**`test_cli.py` integration cases:**
```python
def test_apply_missing_config_file():
    result = runner.invoke(app, ["apply", "nonexistent_xyz.yaml"])
    assert result.exit_code != 0

def test_apply_invalid_config(tmp_path):
    bad = tmp_path / "bad.yaml"
    bad.write_text("subnet: 192.168.1.0/24\n")  # missing smb, credentials, motion_detection
    result = runner.invoke(app, ["apply", str(bad)])
    assert result.exit_code == 2
    assert "Error:" in result.output or "Error:" in (result.stderr or "")
```

### Previous Story Learnings (from Stories 1.1 and 1.2)

- **`list` renamed to `list_cameras`** with `@app.command(name="list")` — keep this.
- **`field(repr=False)`** on `password` and `smb_password` in `CameraConfig` — already in place, do not remove.
- **Module boundary**: `print()` forbidden in `cli.py` — use `typer.echo(..., err=True)` for stderr.
- **`typer.Exit(code=2)`** not `sys.exit(2)` — Typer-idiomatic way to exit with a code.
- **Deferred items addressed in this story** (from Story 1.1 code review deferred-work.md):
  - `config` Path argument: add `exists=True, file_okay=True, dir_okay=False, readable=True`
  - `--subnet` CIDR validation: add `_validate_subnet` callback
- **venv path:** `.venv/Scripts/python -m pytest` on Windows.
- **Running a single test file:** `.venv/Scripts/python -m pytest tests/test_config.py -v`

### Architecture Constraints

- `ConfigError` propagates from `config.py` → `cli.py` only. `executor.py` (Story 3.4) catches all camera-level errors separately.
- `cli.py` exits with code 2 on `ConfigError` — this is the only place code-2 exits for config failures.
- `reporter.py` (Story 3.5) owns per-camera output and summary. For startup errors (config failures), `typer.echo(err=True)` in `cli.py` is acceptable — it's a startup guard, not camera output.
- `ipaddress` is Python stdlib — no new dependency in `pyproject.toml` needed.

### References

- [Source: architecture.md#Error Handling Patterns] — ConfigError propagation, cli.py catching at startup
- [Source: architecture.md#Implementation Patterns] — Module boundary rules, anti-patterns
- [Source: epics.md#Story 1.3] — Acceptance criteria
- [Source: prd.md#Exit Codes] — code 2 = fatal error (config invalid)
- [Source: deferred-work.md] — Story 1.1 review items addressed here (Path exists=True, subnet CIDR validation)

## Code Review Findings (2026-04-01)

### Reviewer: claude-sonnet-4-6

### Triage Summary: 0 decision-needed · 3 patch · 1 defer · 4 dismissed

---

**PATCH-1 — `timeout: 0` silently replaced with 5**
- File: `src/cctv/config.py:76`
- Code: `timeout=int(data.get("timeout") or 5)`
- Issue: `0` is falsy in Python, so `timeout: 0` in YAML is treated as absent and replaced with `5`. This is a silent data corruption bug — the user's explicit zero is ignored.
- Fix: `raw = data.get("timeout"); timeout=int(raw) if raw is not None else 5`

**PATCH-2 — null section value causes unhandled `TypeError` (not `ConfigError`)**
- File: `src/cctv/config.py:51,56,61`
- Code: `creds = data["credentials"]` (and similar for `smb`, `motion_detection`)
- Issue: If a user writes `credentials: null` in YAML, `creds` becomes `None`. The subsequent `key not in creds` then raises `TypeError: argument of type 'NoneType' is not iterable` — an unhandled exception that leaks as a traceback rather than a clean `ConfigError`.
- Fix: After each section assignment, add: `if not isinstance(creds, dict): raise ConfigError("Missing required key: credentials.username")`  — or more precisely: `raise ConfigError(f"'{section_name}' must be a YAML mapping, got null")`

**PATCH-3 — bare integer `subnet` passes CIDR validation, stored as `int` in `str` field**
- File: `src/cctv/config.py:46-49`
- Code: `ipaddress.ip_network(data["subnet"], strict=False)`
- Issue: `subnet: 192` (bare integer) is a valid YAML integer. `ipaddress.ip_network(192)` does not raise — it returns `IPv4Network('0.0.0.192/32')`. The integer is then stored in `CameraConfig.subnet` which is typed `str`, silently breaking downstream consumers.
- Fix: Add `isinstance(data["subnet"], str)` guard before the CIDR check: `if not isinstance(data["subnet"], str): raise ConfigError(f"Invalid subnet: must be a string CIDR, got {type(data['subnet']).__name__}")`

---

**DEFER-1 — `motion_detection.sensitivity` non-integer string causes unhandled `ValueError`**
- File: `src/cctv/config.py:75`
- Code: `motion_sensitivity=int(motion["sensitivity"])`
- Issue: `sensitivity: "high"` passes the key-presence check but raises bare `ValueError` from `int()`, not `ConfigError`. Low real-world risk since YAML integers are common; string values would be a clear user error.
- Deferred to: Story 3.3 (motion detection configuration) or a future hardening pass.

---

**DISMISSED (4 items):**
- `yaml.safe_load` not `yaml.load` — correct, no issue.
- `PermissionError` catch — correct and complete.
- `field(repr=False)` on secrets — already applied in Story 1.2 review, present and correct.
- `exists=True` on Typer argument — correct, defensive double-guard with `load_config` is appropriate.

## Dev Agent Record

### Agent Model Used

claude-sonnet-4-6

### Debug Log References

- No issues encountered. All tasks completed on first attempt.

### Completion Notes List

- `src/cctv/config.py`: added `ipaddress` import; wrapped all failure modes in `ConfigError` (FileNotFoundError, PermissionError, YAMLError, None/empty, missing top-level keys, missing nested keys, invalid CIDR); fixed `timeout: null` with `or 5` pattern
- `src/cctv/cli.py`: added `_validate_subnet` callback; `config` argument now uses `exists=True, file_okay=True, dir_okay=False, readable=True`; `apply()` wraps `load_config` in `try/except ConfigError` → `typer.echo(err=True)` + `typer.Exit(code=2)`; also addresses two Story 1.1 deferred items (Path existence, CIDR validation)
- `tests/test_config.py`: added 7 error-case tests (file not found, empty file, missing top-level key, missing nested key, invalid subnet, invalid YAML, timeout null)
- `tests/test_cli.py`: added 2 integration tests (missing config file, invalid config exits 2)
- 15 pytest tests pass (10 config + 5 CLI), 0 failures, 0 regressions

### File List

- src/cctv/config.py
- src/cctv/cli.py
- tests/test_config.py
- tests/test_cli.py
