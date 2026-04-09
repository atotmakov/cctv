# Story 3.5: Per-Camera Output, Summary, and Exit Codes

Status: done

## Story

As a home sysadmin,
I want clear per-camera status output and a summary line after every apply run,
So that I know exactly what happened without needing to inspect anything else.

## Acceptance Criteria

1. **Given** an apply run completes across multiple cameras, **when** results are printed, **then** each camera produces exactly one output line: `<IP>  <model>  applied (<settings>) | no change | FAILED — <reason>` **and** a summary line shows counts: `Summary: N applied, M no change, K failed` **and** all status lines go to stdout.

2. **Given** all cameras succeed (applied or no change), **when** `cctv apply` exits, **then** the exit code is `0`.

3. **Given** one or more cameras fail, **when** `cctv apply` exits, **then** the exit code is `1` **and** the summary line includes a re-run hint.

## Tasks / Subtasks

- [x] Modify `src/cctv/reporter.py` — add `print_apply_results` (AC: 1, 2, 3)
  - [x] Add `from cctv.reconciler import CameraResult, CameraStatus` import
  - [x] Add `import sys` at module top (for future stderr — kept for architecture compliance)
  - [x] Define `print_apply_results(results: list[CameraResult]) -> int`
    - [x] For each result, print one status line to stdout:
      - APPLIED: `{ip}  {model}  applied ({', '.join(settings_changed)})`
      - NO_CHANGE: `{ip}  {model}  no change`
      - FAILED: `{ip}  {model}  FAILED — {error}`
    - [x] Compute `n_applied`, `n_no_change`, `n_failed` counts
    - [x] Print summary: `Summary: {n_applied} applied, {n_no_change} no change, {n_failed} failed`
    - [x] Append ` — re-run to retry failed cameras` to summary when `n_failed > 0`
    - [x] Return `1` if any `n_failed > 0`, else `0`
- [x] Add tests to `tests/test_reporter.py` (AC: 1, 2, 3)
  - [x] Import `CameraResult, CameraStatus` from `cctv.reconciler` and `print_apply_results` from `cctv.reporter`
  - [x] `test_print_apply_results_applied` — APPLIED result → line has ip, model, "applied", settings in parens (AC: 1)
  - [x] `test_print_apply_results_no_change` — NO_CHANGE result → line has "no change" (AC: 1)
  - [x] `test_print_apply_results_failed` — FAILED result → line has "FAILED —" and error text (AC: 1)
  - [x] `test_print_apply_results_summary_counts` — 2 APPLIED + 1 NO_CHANGE + 1 FAILED → summary shows correct counts (AC: 1)
  - [x] `test_print_apply_results_exit_0_all_succeed` — all APPLIED/NO_CHANGE → returns 0 (AC: 2)
  - [x] `test_print_apply_results_exit_1_any_failed` — one FAILED → returns 1 (AC: 3)
  - [x] `test_print_apply_results_rerun_hint_when_failed` — any FAILED → summary contains "re-run" (AC: 3)
  - [x] `test_print_apply_results_empty` — empty results → summary `0 applied, 0 no change, 0 failed`, returns 0
- [x] Modify `src/cctv/cli.py` — wire reporter output and exit code (AC: 2, 3)
  - [x] Replace `# reporter.print_apply_results(results)  — Story 3.5` comment with actual call
  - [x] `exit_code = reporter.print_apply_results(results)`
  - [x] `raise typer.Exit(code=exit_code)`
- [x] Update `tests/test_cli.py` — apply exit code tests (AC: 2, 3)
  - [x] Add `test_apply_exits_1_when_cameras_fail` — mock apply_all returning FAILED results → exit code 1
  - [x] Verify `test_apply_runs_executor` still exits 0 (APPLIED results → exit 0)
- [x] Run `pytest` — all tests pass, no regressions

## Dev Notes

### reporter.py — Full Implementation

```python
# src/cctv/reporter.py
from __future__ import annotations

import sys

from cctv.reconciler import CameraResult, CameraStatus
from cctv.scanner import DiscoveredCamera


def print_camera_list(cameras: list[DiscoveredCamera]) -> None:
    """Print per-camera lines and summary count to stdout."""
    for cam in cameras:
        print(f"{cam.ip}  {cam.model}  (reachable)")
    n = len(cameras)
    if n == 0:
        print("No Axis cameras found")
    else:
        noun = "camera" if n == 1 else "cameras"
        print(f"Found {n} Axis {noun}")


def print_apply_results(results: list[CameraResult]) -> int:
    """Print per-camera apply results and summary. Returns exit code (0 or 1)."""
    for result in results:
        if result.status == CameraStatus.APPLIED:
            settings = ", ".join(result.settings_changed)
            print(f"{result.ip}  {result.model}  applied ({settings})")
        elif result.status == CameraStatus.NO_CHANGE:
            print(f"{result.ip}  {result.model}  no change")
        else:  # FAILED
            print(f"{result.ip}  {result.model}  FAILED — {result.error}")

    n_applied = sum(1 for r in results if r.status == CameraStatus.APPLIED)
    n_no_change = sum(1 for r in results if r.status == CameraStatus.NO_CHANGE)
    n_failed = sum(1 for r in results if r.status == CameraStatus.FAILED)

    summary = f"Summary: {n_applied} applied, {n_no_change} no change, {n_failed} failed"
    if n_failed > 0:
        summary += " — re-run to retry failed cameras"
    print(summary)

    return 1 if n_failed > 0 else 0
```

**Why `import sys` at module top:** Architecture mandates reporter.py is the module that owns all stdout/stderr. Adding `sys` now keeps the module structurally ready per the architecture spec; it is not used for per-camera output in this story but follows the boundary rule.

### cli.py — apply Command After This Story

```python
@app.command()
def apply(
    config: Path = typer.Argument(...),
    subnet: Optional[str] = typer.Option(None, "--subnet", ...),
) -> None:
    """Apply config to all discovered cameras."""
    try:
        cfg = load_config(config)
    except ConfigError as e:
        typer.echo(f"Error: {e}", err=True)
        raise typer.Exit(code=2)
    auth = HTTPDigestAuth(cfg.username, cfg.password)
    effective_subnet = subnet or cfg.subnet
    cameras = scanner.scan(effective_subnet, auth, cfg.timeout)
    results = executor.apply_all(cameras, cfg, auth)
    exit_code = reporter.print_apply_results(results)
    raise typer.Exit(code=exit_code)
```

**Exit code contract:**
- `0` — all cameras APPLIED or NO_CHANGE
- `1` — one or more cameras FAILED
- `2` — fatal config error (already handled, unchanged)

### test_reporter.py — New Test Patterns

```python
from cctv.reconciler import CameraResult, CameraStatus
from cctv.reporter import print_apply_results, print_camera_list

CAM_IP = "192.168.1.101"
CAM_MODEL = "AXIS P3245-V"


def _result(status: CameraStatus, settings: list[str] | None = None, error: str | None = None) -> CameraResult:
    return CameraResult(
        ip=CAM_IP,
        model=CAM_MODEL,
        status=status,
        settings_changed=settings or [],
        error=error,
    )


def test_print_apply_results_applied(capsys) -> None:
    exit_code = print_apply_results([_result(CameraStatus.APPLIED, ["smb_ip", "motion"])])
    out = capsys.readouterr().out
    assert CAM_IP in out
    assert CAM_MODEL in out
    assert "applied" in out
    assert "smb_ip" in out
    assert "motion" in out
    assert exit_code == 0


def test_print_apply_results_no_change(capsys) -> None:
    exit_code = print_apply_results([_result(CameraStatus.NO_CHANGE)])
    out = capsys.readouterr().out
    assert "no change" in out
    assert exit_code == 0


def test_print_apply_results_failed(capsys) -> None:
    exit_code = print_apply_results([_result(CameraStatus.FAILED, error="Connection timeout")])
    out = capsys.readouterr().out
    assert "FAILED" in out
    assert "Connection timeout" in out
    assert exit_code == 1


def test_print_apply_results_summary_counts(capsys) -> None:
    results = [
        _result(CameraStatus.APPLIED, ["smb_ip"]),
        _result(CameraStatus.APPLIED, ["motion"]),
        _result(CameraStatus.NO_CHANGE),
        _result(CameraStatus.FAILED, error="timeout"),
    ]
    print_apply_results(results)
    out = capsys.readouterr().out
    assert "2 applied" in out
    assert "1 no change" in out
    assert "1 failed" in out


def test_print_apply_results_exit_0_all_succeed(capsys) -> None:
    results = [_result(CameraStatus.APPLIED, ["smb_ip"]), _result(CameraStatus.NO_CHANGE)]
    exit_code = print_apply_results(results)
    assert exit_code == 0


def test_print_apply_results_exit_1_any_failed(capsys) -> None:
    results = [_result(CameraStatus.APPLIED, ["smb_ip"]), _result(CameraStatus.FAILED, error="timeout")]
    exit_code = print_apply_results(results)
    assert exit_code == 1


def test_print_apply_results_rerun_hint_when_failed(capsys) -> None:
    print_apply_results([_result(CameraStatus.FAILED, error="timeout")])
    out = capsys.readouterr().out
    assert "re-run" in out


def test_print_apply_results_empty(capsys) -> None:
    exit_code = print_apply_results([])
    out = capsys.readouterr().out
    assert "0 applied" in out
    assert "0 no change" in out
    assert "0 failed" in out
    assert exit_code == 0
```

### test_cli.py — New Exit Code Test

```python
def test_apply_exits_1_when_cameras_fail(tmp_path: Path) -> None:
    cfg = tmp_path / "cameras.yaml"
    cfg.write_text(VALID_CONFIG)
    cameras = [DiscoveredCamera(ip="192.168.1.101", model="AXIS P3245-V")]
    results = [CameraResult(ip="192.168.1.101", model="AXIS P3245-V", status=CameraStatus.FAILED, error="timeout")]
    with patch("cctv.cli.scanner.scan", return_value=cameras), \
         patch("cctv.cli.executor.apply_all", return_value=results):
        result = runner.invoke(app, ["apply", str(cfg)])
    assert result.exit_code == 1
```

**Note:** No need to mock `reporter.print_apply_results` here — the real function is called with the FAILED results and returns 1.

### Patch Targets

- `cctv.cli.reporter.print_apply_results` — when testing the CLI and needing to control the return value
- No patching needed in `test_reporter.py` — tests call `print_apply_results` directly

### Import Circular-Check

`reporter.py` currently imports `from cctv.scanner import DiscoveredCamera`. Adding `from cctv.reconciler import CameraResult, CameraStatus` is safe:
- `reconciler.py` imports `from cctv import vapix`, `from cctv.config import ...`, `from cctv.scanner import ...`
- No module in that chain imports `reporter.py` → no circular import.

### Architecture Constraints — CRITICAL

- **`print()` ONLY in `reporter.py`** — no output anywhere else
- **`import sys` at module top** — architecture compliance; actual `sys.stderr` usage is optional per-story
- **All status lines → stdout** — use plain `print()` (goes to sys.stdout by default)
- **Return value is the exit code** — caller (`cli.py`) uses it directly with `raise typer.Exit(code=exit_code)`
- **`src/cctv/__init__.py` remains EMPTY**
- **DO NOT** add `sys.exit()` in reporter — cli.py owns exit via `typer.Exit`
- **Never include credentials in output** — `result.error` is already sanitized by executor; no extra guard needed here

### Output Format Reference

```
192.168.1.101  AXIS P3245-V  applied (smb_ip, motion)
192.168.1.102  AXIS P3245-V  no change
192.168.1.103  AXIS P3245-V  FAILED — Connection timeout to 192.168.1.103
Summary: 1 applied, 1 no change, 1 failed — re-run to retry failed cameras
```

All-success output:
```
192.168.1.101  AXIS P3245-V  applied (smb_ip)
192.168.1.102  AXIS P3245-V  no change
Summary: 1 applied, 1 no change, 0 failed
```

### Previous Story Learnings (Stories 1.1–3.4)

- `from __future__ import annotations` at top of every modified module
- `capsys.readouterr().out` for stdout assertions in reporter tests
- `capsys.readouterr().err` for stderr assertions (not used in this story but available)
- `typer.Exit(code=N)` is caught by CliRunner as `result.exit_code == N`
- Patch at import site: `cctv.cli.reporter.print_apply_results` — cli.py imports reporter as module
- **venv path on Windows:** `.venv/Scripts/python -m pytest`
- `{**fixture, key: val}` copy pattern — NEVER mutate fixture dicts

### Files to Create / Modify

- `src/cctv/reporter.py` — **MODIFY** (add `print_apply_results`)
- `tests/test_reporter.py` — **MODIFY** (add 8 new tests)
- `src/cctv/cli.py` — **MODIFY** (replace comment with real reporter call + exit code)
- `tests/test_cli.py` — **MODIFY** (add `test_apply_exits_1_when_cameras_fail`)

### References

- [epics.md#Story 3.5] — acceptance criteria, FR21–FR26
- [architecture.md#Module Responsibility Boundaries] — reporter owns all print/output
- [architecture.md#Process Patterns] — stdout/stderr discipline
- [3-4-failure-isolated-apply-executor.md] — executor.apply_all signature and CameraResult structure

## Dev Agent Record

### Agent Model Used

claude-sonnet-4-6

### Debug Log References

- No issues encountered. All tasks completed on first attempt.

### Completion Notes List

- `src/cctv/reporter.py`: added `import sys` and `from cctv.reconciler import CameraResult, CameraStatus`; added `print_apply_results(results) -> int` — APPLIED prints `applied (settings)`, NO_CHANGE prints `no change`, FAILED prints `FAILED — error`; summary line with counts; appends re-run hint when n_failed > 0; returns 1 if any failed, 0 otherwise
- `tests/test_reporter.py`: added module-level imports for `CameraResult, CameraStatus, print_apply_results`; added `_result()` helper; 8 new tests covering APPLIED/NO_CHANGE/FAILED output format, summary counts, exit code 0/1, re-run hint, empty results
- `src/cctv/cli.py`: replaced `# reporter.print_apply_results(results)  — Story 3.5` with `exit_code = reporter.print_apply_results(results)` + `raise typer.Exit(code=exit_code)`
- `tests/test_cli.py`: added `test_apply_exits_1_when_cameras_fail` — FAILED results → exit code 1 (real reporter called, no mock needed)
- 77 pytest tests pass (11 CLI + 10 config + 7 executor + 15 reconciler + 12 reporter + 7 scanner + 15 vapix), 0 failures, 0 regressions

### File List

- src/cctv/reporter.py
- tests/test_reporter.py
- src/cctv/cli.py
- tests/test_cli.py

### Review Findings

- [x] [Review][Patch] `else` branch in `print_apply_results` implicitly catches unknown enum values [src/cctv/reporter.py:29] — replace `else: # FAILED` with `elif result.status == CameraStatus.FAILED:` + `else: raise ValueError(...)` to make unknown-status a loud failure
- [x] [Review][Patch] `test_print_apply_results_applied` missing exact format assertion [tests/test_reporter.py] — add assertion for `f"{_IP}  {_MODEL}  applied (smb_ip, motion)"` to verify double-space separator and parens format, not just substring presence
- [x] [Review][Patch] `test_print_apply_results_failed` never asserts combined `"FAILED — <reason>"` [tests/test_reporter.py] — add `assert f"FAILED — Connection timeout" in out` to verify em-dash separator and exact rendering
- [x] [Review][Patch] `test_print_apply_results_summary_counts` never asserts `"Summary:"` prefix [tests/test_reporter.py] — add `assert "Summary:" in out`
- [x] [Review][Patch] `test_apply_exits_1_when_cameras_fail` has no output content assertions [tests/test_cli.py] — add assertions for "FAILED" and "re-run" in `result.output` to cover AC1 and AC3 at CLI integration level
- [x] [Review][Defer] `APPLIED` with empty `settings_changed` renders as `applied ()` [src/cctv/reporter.py:25] — not reachable in practice (reconciler returns NO_CHANGE when nothing changed); defer to hardening pass
- [x] [Review][Defer] `FAILED` with `error=None` renders as `"FAILED — None"` [src/cctv/reporter.py:30] — executor always sets `error=str(exc)` for FAILED results; pre-existing type gap; defer to hardening pass
- [x] [Review][Defer] `model=None` interpolated in f-strings without guard [src/cctv/reporter.py:26,28,30] — scanner always provides model; pre-existing `Optional[str]` type gap; defer to hardening pass
- [x] [Review][Defer] `apply` CLI produces exit 0 with empty-fleet summary when no cameras found [src/cctv/cli.py:73] — out of Story 3.5 scope; spec does not define apply behavior for zero cameras; deferred
- [x] [Review][Defer] `typer.echo` in cli.py bypasses reporter.py for config errors — pre-existing from Story 1.3; architecture intent is "print() only in reporter.py"; `typer.echo` used for Typer-idiomatic error output; deferred
- [x] [Review][Defer] `print_apply_results` iterates results 4× — loop + 3 sum() calls — [src/cctv/reporter.py:23] — list type enforced by annotation; no practical impact; defer to hardening pass
- [x] [Review][Defer] AC3 re-run hint not tested at CLI integration level — covered by Patch P5 if applied; otherwise defer
