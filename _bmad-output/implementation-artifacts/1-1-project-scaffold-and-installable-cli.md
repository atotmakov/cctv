# Story 1.1: Project Scaffold and Installable CLI

Status: done

## Story

As a home sysadmin,
I want to install `cctv` via pip and run `cctv --help`,
so that I can confirm the tool is installed and see available commands.

## Acceptance Criteria

1. **Given** the repo is cloned and Python 3.11+ is available, **when** I run `pip install -e .`, **then** the `cctv` entry point is available on PATH and `cctv --help` outputs the available commands (`list`, `apply`) without error.

2. **Given** the project structure follows the src layout, **when** pytest is run, **then** all test files are discoverable and importable without path errors.

## Tasks / Subtasks

- [x] Create `pyproject.toml` with correct metadata, dependencies, entry point, and build system (AC: 1)
  - [x] name = "cctv", requires-python = ">=3.11"
  - [x] dependencies: typer>=0.24, requests>=2.33, pyyaml>=6.0
  - [x] optional-dependencies.dev: pytest>=9.0
  - [x] scripts: cctv = "cctv.cli:app"
  - [x] build-system: setuptools>=68
- [x] Create src/cctv/__init__.py — EMPTY FILE, no content (AC: 1, 2)
- [x] Create src/cctv/cli.py — Typer app with stubbed `list` and `apply` commands (AC: 1)
  - [x] `app = typer.Typer()`
  - [x] `@app.command()` for `list` with `--subnet` option (optional str, default None)
  - [x] `@app.command()` for `apply` with `config` path argument and `--subnet` option
  - [x] Stubs raise `NotImplementedError` or `typer.echo("not implemented")` — do NOT implement logic here
- [x] Create tests/__init__.py — EMPTY FILE (AC: 2)
- [x] Create tests/conftest.py — placeholder with TODO comment for shared fixtures (AC: 2)
- [x] Create .gitignore — exclude cameras.yaml, .venv, __pycache__, dist/, *.egg-info/ (AC: 1)
- [x] Create cameras.yaml.example — reference config documenting all keys (AC: 1)
- [x] Create README.md — install instructions, usage, plaintext credentials warning (AC: 1)
- [x] Verify `pip install -e .` completes without error (AC: 1)
- [x] Verify `cctv --help` shows `list` and `apply` subcommands (AC: 1)
- [x] Verify `cctv list --help` and `cctv apply --help` work without error (AC: 1)
- [x] Verify `pytest` discovers test files with zero import errors (AC: 2)

## Dev Notes

### Critical Architecture Constraints

**Module boundary rules — enforced from the very first commit:**
- `import requests` is ONLY allowed in `src/cctv/vapix.py` — never in any other module
- `print()` / `sys.stdout.write()` is ONLY allowed in `src/cctv/reporter.py` — never elsewhere
- `__init__.py` files are EMPTY — no re-exports, no package-level imports, no `__all__`
- These rules must be respected even in stub implementations

**Typer version and pattern (Typer 0.24.1):**
- Commands are declared as typed Python functions with `@app.command()` decorator
- Arguments use type hints — `typer.Argument()` for positional, `typer.Option()` for flags
- `cctv list` accepts `--subnet` as an optional override (type: `Optional[str] = None`)
- `cctv apply` accepts `config` as a required `Path` argument and optional `--subnet`
- Do NOT use `typer.run()` — use `app = typer.Typer()` with subcommands

**pyproject.toml — exact structure required:**
```toml
[project]
name = "cctv"
version = "0.1.0"
requires-python = ">=3.11"
dependencies = [
    "typer>=0.24",
    "requests>=2.33",
    "pyyaml>=6.0",
]

[project.optional-dependencies]
dev = ["pytest>=9.0"]

[project.scripts]
cctv = "cctv.cli:app"

[build-system]
requires = ["setuptools>=68"]
build-backend = "setuptools.backends.legacy:build"
```

**cameras.yaml.example — must document ALL config keys:**
```yaml
subnet: 192.168.1.0/24
credentials:
  username: root
  password: changeme  # plaintext — do not commit cameras.yaml to public repos
smb:
  ip: 192.168.1.10
  share: /mnt/cctv
  username: smbuser
  password: smbpass
motion_detection:
  enabled: true
  sensitivity: 50
timeout: 5  # per-camera connection timeout in seconds (default: 5)
```

**README.md must include:**
1. Install: `pip install git+https://github.com/atotmakov/cctv.git` (or `pip install -e .` for dev)
2. Usage: `cctv list [--subnet CIDR]` and `cctv apply config.yaml [--subnet CIDR]`
3. Config: reference to cameras.yaml.example
4. ⚠️ Security warning: "cameras.yaml contains plaintext credentials — do not commit to public repos"

### Project Structure to Create

```
cctv/
├── pyproject.toml
├── README.md
├── cameras.yaml.example
├── .gitignore
├── src/
│   └── cctv/
│       ├── __init__.py       ← EMPTY
│       └── cli.py            ← Typer app stub
└── tests/
    ├── __init__.py           ← EMPTY
    └── conftest.py           ← Placeholder, fixtures added in later stories
```

Modules `config.py`, `scanner.py`, `vapix.py`, `reconciler.py`, `executor.py`, `reporter.py` are created in subsequent stories — do NOT create them now.

### cli.py Stub Pattern

```python
import typer
from typing import Optional
from pathlib import Path

app = typer.Typer()


@app.command()
def list(
    subnet: Optional[str] = typer.Option(None, "--subnet", help="Override subnet (CIDR)"),
) -> None:
    """Discover Axis cameras on the subnet."""
    raise NotImplementedError


@app.command()
def apply(
    config: Path = typer.Argument(..., help="Path to cameras.yaml config file"),
    subnet: Optional[str] = typer.Option(None, "--subnet", help="Override subnet (CIDR)"),
) -> None:
    """Apply config to all discovered cameras."""
    raise NotImplementedError


if __name__ == "__main__":
    app()
```

### .gitignore Content

```
cameras.yaml
.venv/
__pycache__/
*.pyc
dist/
*.egg-info/
.pytest_cache/
```

### Testing Approach

This story has no business logic to unit test. The verification is:
- `pip install -e .` succeeds (no import errors, entry point registered)
- `cctv --help` shows `list` and `apply` without crashing
- `pytest` runs and discovers `tests/` without ImportError

The test suite starts empty — `conftest.py` is a placeholder. Actual test fixtures (`CameraConfig`, mock auth, mock VAPIX responses) are added in Story 1.2 and 1.4 as those modules are built.

### References

- [Source: architecture.md#Starter Template Evaluation] — Typer + src layout + pytest decision
- [Source: architecture.md#Project Structure & Boundaries] — Complete directory structure
- [Source: architecture.md#Implementation Patterns & Consistency Rules] — Module boundary rules
- [Source: architecture.md#Distribution] — pip install git+... for MVP
- [Source: epics.md#Story 1.1] — Acceptance criteria and story statement
- [Source: prd.md#Config Schema] — cameras.yaml.example keys

## Dev Agent Record

### Agent Model Used

claude-sonnet-4-6

### Debug Log References

- build-backend fixed: `setuptools.backends.legacy:build` → `setuptools.build_meta` (older setuptools in venv did not support the legacy backend path)
- pytest testpaths configured: added `[tool.pytest.ini_options] testpaths = ["tests"]` to prevent pytest from collecting 68 BMAD framework tests from `_bmad/`
- Added `tests/test_cli.py` with 3 smoke tests using `typer.testing.CliRunner` — verifies `--help`, `list --help`, `apply --help` all exit 0

### Completion Notes List

- All 7 files created: pyproject.toml, src/cctv/__init__.py, src/cctv/cli.py, tests/__init__.py, tests/conftest.py, .gitignore, cameras.yaml.example, README.md
- `pip install -e ".[dev]"` succeeds; installed: typer-0.24.1, requests-2.33.1, pyyaml-6.0.3, pytest-9.0.2
- `cctv --help` shows `list` and `apply` commands with correct descriptions
- `cctv list --help` shows `--subnet` option; `cctv apply --help` shows `config` argument + `--subnet` option
- 3 pytest tests pass (0 failures, 0 errors)
- Module boundary rules respected from day 1: no `import requests`, no `print()` in cli.py

### File List

- pyproject.toml
- src/cctv/__init__.py
- src/cctv/cli.py
- tests/__init__.py
- tests/conftest.py
- tests/test_cli.py
- .gitignore
- cameras.yaml.example
- README.md

### Review Findings

- [x] [Review][Patch] `list` function shadows Python built-in `list` [src/cctv/cli.py:9]
- [x] [Review][Defer] `config` Path argument has no existence check [src/cctv/cli.py:18] — deferred, pre-existing; scope is Story 1.3 config validation
- [x] [Review][Defer] No CIDR validation on `--subnet` argument [src/cctv/cli.py:10,19] — deferred, pre-existing; scope is Story 1.3 config validation
- [x] [Review][Defer] `.gitignore` only catches root-level `cameras.yaml` — deferred, pre-existing; very low risk, cameras.yaml is a root-level config by convention
