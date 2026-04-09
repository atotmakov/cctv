# Story 1.4: VAPIX API Client (Get and Set Parameters)

Status: done

## Story

As a home sysadmin,
I want the tool to communicate with Axis cameras via the VAPIX 3 API,
So that it can read and write camera settings reliably using HTTP Digest Auth.

## Acceptance Criteria

1. **Given** a reachable Axis camera at a known IP, **when** `get_params(ip, group, auth, timeout)` is called, **then** the current parameter values for that group are returned as `dict[str, str]`, **and** HTTP Digest Auth is used on every request.

2. **Given** a VAPIX SET call receives a non-2xx response, **when** `set_params(ip, params, auth, timeout)` is called, **then** a `VapixError` is raised with the response status and reason, **and** no raw credential values appear in the error message.

3. **Given** the camera does not respond within the configured timeout, **when** any VAPIX call is made, **then** a `VapixError` is raised (connection timeout), **and** the hardcoded timeout is never used — timeout always comes from `CameraConfig`.

## Tasks / Subtasks

- [x] Create `src/cctv/vapix.py` — VAPIX 3 client (AC: 1, 2, 3)
  - [x] Define `VapixError(Exception)` — top of file, no imports needed beyond stdlib for the class
  - [x] Implement `get_params(ip, group, auth, timeout) -> dict[str, str]`
    - [x] GET `http://{ip}/axis-cgi/param.cgi?action=list&group={group}` with `auth=auth, timeout=timeout`
    - [x] Catch `requests.exceptions.Timeout` → raise `VapixError(f"Connection timeout to {ip}")`
    - [x] Catch `requests.exceptions.ConnectionError` → raise `VapixError(f"Connection error to {ip}: {e}")`
    - [x] Non-2xx status → raise `VapixError(f"GET {group} from {ip} failed: {resp.status_code} {resp.reason}")`
    - [x] Parse response body via `_parse_param_response(resp.text)` → return `dict[str, str]`
  - [x] Implement `set_params(ip, params, auth, timeout) -> None`
    - [x] POST `http://{ip}/axis-cgi/param.cgi` with query params `{"action": "update", **params}`, `auth=auth, timeout=timeout`
    - [x] Catch `requests.exceptions.Timeout` → raise `VapixError(f"Connection timeout to {ip}")`
    - [x] Catch `requests.exceptions.ConnectionError` → raise `VapixError(f"Connection error to {ip}: {e}")`
    - [x] Non-2xx status → raise `VapixError(f"SET params on {ip} failed: {resp.status_code} {resp.reason}")`
  - [x] Implement `_parse_param_response(text: str) -> dict[str, str]` (private helper)
    - [x] Split on newlines; for each line with `=`, partition on first `=` → `{key.strip(): value.strip()}`
    - [x] Return empty dict for empty/blank response (not an error)
  - [x] **FORBIDDEN in this file:** `print()`, `sys.stdout.write()` — no output
  - [x] **REQUIRED in this file:** `import requests` — this is the ONLY module that may import requests
- [x] Update `tests/conftest.py` — add Story 1.4 fixtures (remove TODO comments)
  - [x] Add `mock_auth` fixture: returns `HTTPDigestAuth("root", "testpass")`
  - [x] Add `vapix_brand_response` fixture: returns typical VAPIX brand response string
- [x] Create `tests/test_vapix.py` — full test coverage (AC: 1, 2, 3)
  - [x] `test_get_params_success` — mock `requests.get` returning 200 with valid param body → assert result dict matches parsed params
  - [x] `test_get_params_non_2xx` — mock `requests.get` returning 401 → assert `VapixError` raised, message contains `"401"`
  - [x] `test_get_params_timeout` — mock `requests.get` raising `requests.exceptions.Timeout` → assert `VapixError` raised
  - [x] `test_get_params_connection_error` — mock `requests.get` raising `requests.exceptions.ConnectionError` → assert `VapixError` raised
  - [x] `test_set_params_success` — mock `requests.post` returning 200 → assert no exception raised
  - [x] `test_set_params_non_2xx` — mock `requests.post` returning 400 → assert `VapixError` raised
  - [x] `test_set_params_timeout` — mock `requests.post` raising `requests.exceptions.Timeout` → assert `VapixError` raised
  - [x] `test_set_params_connection_error` — mock `requests.post` raising `requests.exceptions.ConnectionError` → assert `VapixError` raised
  - [x] `test_parse_param_response_typical` — call `_parse_param_response` directly with typical VAPIX body → assert dict matches expected
  - [x] `test_parse_param_response_empty` — empty string → assert `{}` returned (no exception)
  - [x] `test_parse_param_response_blank_lines` — response with blank lines → assert blank lines skipped
  - [x] `test_no_credentials_in_error_get` — mock 401 GET response → catch `VapixError`, assert message does not contain "testpass"
  - [x] `test_no_credentials_in_error_set` — mock 401 POST response → catch `VapixError`, assert message does not contain "testpass"
- [x] Run `pytest` — all tests pass, no regressions in existing tests

## Code Review Findings (2026-04-02)

### Reviewer: claude-sonnet-4-6

### Triage Summary: 0 decision-needed · 2 patch · 3 defer · 7 dismissed

- [x] [Review][Patch] Uncaught `requests.exceptions.RequestException` subclasses escape as non-`VapixError` [src/cctv/vapix.py:16-27, 33-44] — fixed: added `except requests.exceptions.RequestException as e: raise VapixError(f"Request error to {ip}: {e}")` fallback in both `get_params` and `set_params`; added `test_get_params_request_exception_fallback` and `test_set_params_request_exception_fallback`
- [x] [Review][Patch] `set_params` query-params dict allows caller to override `action` key [src/cctv/vapix.py:37] — fixed: changed to `params={**params, "action": "update"}` so action always wins
- [x] [Review][Defer] Plaintext `http://` — VAPIX response bodies unencrypted [src/cctv/vapix.py:14,32] — deferred, pre-existing architectural decision (architecture.md NFR8 specifies Digest Auth, not TLS)
- [x] [Review][Defer] `_parse_param_response` doesn't detect VAPIX application-level error body in HTTP 200 OK [src/cctv/vapix.py:48-54] — deferred, requires hardware verification of Axis firmware error response formats; flag for Stories 3.2/3.3
- [x] [Review][Defer] `ip` not validated before URL interpolation [src/cctv/vapix.py:14,32] — deferred, IPs flow from scanner over validated CIDR range, not raw user input; low real-world risk

## Dev Notes

### Files to Create / Modify

- `src/cctv/vapix.py` — **CREATE** (new file)
- `tests/test_vapix.py` — **CREATE** (new file)
- `tests/conftest.py` — **MODIFY** (add mock fixtures, remove TODO comments)

### Module Boundary — CRITICAL

`vapix.py` is the **sole module** that may `import requests`. No other module in the project may import requests.
`vapix.py` must **NOT** contain `print()` or `sys.stdout.write()`.
`src/cctv/__init__.py` remains **EMPTY**.

### VAPIX 3 Protocol

**Endpoint:** `http://{ip}/axis-cgi/param.cgi`

**GET (read parameters):**
```
GET /axis-cgi/param.cgi?action=list&group=root.Brand
```
Response body (plain text, not JSON):
```
root.Brand.Brand=AXIS
root.Brand.ProdFullName=AXIS P3245-V
root.Brand.ProdNbr=P3245-V
root.Brand.ProdShortName=P3245-V
root.Brand.WebURL=http://www.axis.com
```

**POST (set parameters):**
```
POST /axis-cgi/param.cgi?action=update&root.Network.Share.Path=/recordings&root.Network.Share.Host=192.168.1.10
```
Success response: `200 OK` with body `"OK\n"` or similar short confirmation.
Failure response: `400` or `401` with plain text error body.

**Authentication:** `requests.auth.HTTPDigestAuth(username, password)` — passed on every call.

### Implementation Pattern

```python
from __future__ import annotations

import requests
from requests.auth import HTTPDigestAuth


class VapixError(Exception):
    """VAPIX API call failed (non-2xx, auth failure, timeout)."""


def get_params(ip: str, group: str, auth: HTTPDigestAuth, timeout: int) -> dict[str, str]:
    url = f"http://{ip}/axis-cgi/param.cgi"
    try:
        resp = requests.get(url, params={"action": "list", "group": group}, auth=auth, timeout=timeout)
    except requests.exceptions.Timeout:
        raise VapixError(f"Connection timeout to {ip}")
    except requests.exceptions.ConnectionError as e:
        raise VapixError(f"Connection error to {ip}: {e}")
    if resp.status_code != 200:
        raise VapixError(f"GET {group} from {ip} failed: {resp.status_code} {resp.reason}")
    return _parse_param_response(resp.text)


def set_params(ip: str, params: dict[str, str], auth: HTTPDigestAuth, timeout: int) -> None:
    url = f"http://{ip}/axis-cgi/param.cgi"
    try:
        resp = requests.post(url, params={"action": "update", **params}, auth=auth, timeout=timeout)
    except requests.exceptions.Timeout:
        raise VapixError(f"Connection timeout to {ip}")
    except requests.exceptions.ConnectionError as e:
        raise VapixError(f"Connection error to {ip}: {e}")
    if resp.status_code != 200:
        raise VapixError(f"SET params on {ip} failed: {resp.status_code} {resp.reason}")


def _parse_param_response(text: str) -> dict[str, str]:
    result: dict[str, str] = {}
    for line in text.splitlines():
        if "=" in line:
            key, _, value = line.partition("=")
            result[key.strip()] = value.strip()
    return result
```

### Test Patterns

**Mocking requests — patch at module level:**
```python
from unittest.mock import MagicMock, patch
from requests.auth import HTTPDigestAuth
from cctv.vapix import VapixError, _parse_param_response, get_params, set_params

AUTH = HTTPDigestAuth("root", "testpass")
BRAND_RESPONSE = "root.Brand.Brand=AXIS\nroot.Brand.ProdNbr=P3245-V\n"

def test_get_params_success():
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.text = BRAND_RESPONSE
    with patch("cctv.vapix.requests.get", return_value=mock_resp) as mock_get:
        result = get_params("192.168.1.101", "root.Brand", AUTH, timeout=5)
    assert result == {"root.Brand.Brand": "AXIS", "root.Brand.ProdNbr": "P3245-V"}
    mock_get.assert_called_once()

def test_get_params_non_2xx():
    mock_resp = MagicMock(status_code=401, reason="Unauthorized")
    with patch("cctv.vapix.requests.get", return_value=mock_resp):
        with pytest.raises(VapixError, match="401"):
            get_params("192.168.1.101", "root.Brand", AUTH, timeout=5)

def test_get_params_timeout():
    import requests as req_lib
    with patch("cctv.vapix.requests.get", side_effect=req_lib.exceptions.Timeout):
        with pytest.raises(VapixError, match="timeout"):
            get_params("192.168.1.101", "root.Brand", AUTH, timeout=5)

def test_no_credentials_in_error():
    mock_resp = MagicMock(status_code=401, reason="Unauthorized")
    with patch("cctv.vapix.requests.get", return_value=mock_resp):
        with pytest.raises(VapixError) as exc_info:
            get_params("192.168.1.101", "root.Brand", AUTH, timeout=5)
    assert "testpass" not in str(exc_info.value)
    assert "root" not in str(exc_info.value)  # "root" in IP is fine, but not as a username
```

**`conftest.py` additions:**
```python
from unittest.mock import MagicMock
from requests.auth import HTTPDigestAuth

@pytest.fixture
def mock_auth() -> HTTPDigestAuth:
    return HTTPDigestAuth("root", "testpass")

@pytest.fixture
def vapix_brand_response() -> str:
    return "root.Brand.Brand=AXIS\nroot.Brand.ProdFullName=AXIS P3245-V\nroot.Brand.ProdNbr=P3245-V\n"
```

### Architecture Constraints

- **`VapixError`** is defined here in `vapix.py`. Future modules (`scanner.py`, `executor.py`) will import it from here.
- **`DiscoveredCamera` dataclass** will be defined in `scanner.py` (Story 2.1) — do NOT create it here.
- **`CameraResult` / `CameraStatus`** will be defined in `executor.py` (Story 3.4) — do NOT create them here.
- The `get_params` function with `group="root.Brand"` will be used by `scanner.py` (Story 2.1) to identify Axis cameras during discovery. This story only implements the client — the caller logic is in future stories.
- **Specific VAPIX parameter names** (e.g., `root.Network.Share.Path`, `root.Motion.M0.Enabled`) are NOT needed in this story. Story 1.4 builds a generic client; Stories 3.2 and 3.3 will supply the exact parameter names after hardware verification.

### Pre-Implementation Note (from Architecture doc)

The architecture flags that exact VAPIX 3 parameter names for SMB (`root.Network.Share.*`) and motion detection (`root.Motion.*`) on firmware 5.51.7.4 **must be verified on real hardware** before Stories 3.2 and 3.3. This story builds the generic client and is **not blocked** by that verification — Story 1.4 uses `root.Brand` (known good) in tests and treats all param names as opaque strings.

### Previous Story Learnings (from Stories 1.1, 1.2, 1.3)

- **`from __future__ import annotations`** — use at top of every module for forward reference support.
- **`field(repr=False)`** pattern — not needed in `vapix.py` (no dataclasses here), but know it's in `CameraConfig` from `config.py`.
- **`pytest` with `tmp_path`** — used for file-based tests; for `vapix.py` tests, use `unittest.mock.patch` instead.
- **venv path on Windows:** `.venv/Scripts/python -m pytest` — use this to run tests.
- **Running a single test file:** `.venv/Scripts/python -m pytest tests/test_vapix.py -v`
- **No `print()`** in any module except `reporter.py`. `vapix.py` is no exception.
- **`typer.Exit(code=2)`** is CLI-only — `vapix.py` has no Typer dependency.

### References

- [architecture.md#VAPIX API Protocol] — endpoint, GET/POST format, Digest Auth pattern
- [architecture.md#Implementation Patterns] — module boundary rules, `VapixError` hierarchy
- [architecture.md#Error Handling Patterns] — propagation rules, credentials in errors forbidden
- [epics.md#Story 1.4] — acceptance criteria
- [architecture.md#Project Structure] — `vapix.py` location, `test_vapix.py` location

## Dev Agent Record

### Agent Model Used

claude-sonnet-4-6

### Debug Log References

- No issues encountered. All tasks completed on first attempt.

### Completion Notes List

- `src/cctv/vapix.py`: created with `VapixError`, `get_params`, `set_params`, `_parse_param_response`; `import requests` is the only place it appears in the codebase; no `print()` calls; timeout always passed from caller
- `tests/test_vapix.py`: 13 tests covering get_params (success, non-2xx, timeout, connection error), set_params (success, non-2xx, timeout, connection error), _parse_param_response (typical, empty, blank lines), and credential hygiene (get + set)
- `tests/conftest.py`: removed TODO comments; added `mock_auth` (HTTPDigestAuth fixture) and `vapix_brand_response` (VAPIX response string fixture)
- 28 pytest tests pass (5 CLI + 10 config + 13 vapix), 0 failures, 0 regressions

### File List

- src/cctv/vapix.py
- tests/test_vapix.py
- tests/conftest.py
