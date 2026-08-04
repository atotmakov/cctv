from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import requests
from requests.auth import HTTPDigestAuth


class VapixError(Exception):
    """VAPIX API call failed (non-2xx, auth failure, timeout)."""


# ---------------------------------------------------------------------------
# param.cgi helpers
# ---------------------------------------------------------------------------

def get_params(ip: str, group: str, auth: HTTPDigestAuth, timeout: int) -> dict[str, str]:
    """GET current parameter values for a VAPIX group. Returns {param: value} or raises VapixError."""
    url = f"http://{ip}/axis-cgi/param.cgi"
    try:
        resp = requests.get(
            url,
            params={"action": "list", "group": group},
            auth=auth,
            timeout=timeout,
        )
    except requests.exceptions.Timeout:
        raise VapixError(f"Connection timeout to {ip}")
    except requests.exceptions.ConnectionError as e:
        raise VapixError(f"Connection error to {ip}: {e}")
    except requests.exceptions.RequestException as e:
        raise VapixError(f"Request error to {ip}: {e}")
    if resp.status_code != 200:
        raise VapixError(f"GET {group} from {ip} failed: {resp.status_code} {resp.reason}")
    return _parse_param_response(resp.text)


def set_params(ip: str, params: dict[str, str], auth: HTTPDigestAuth, timeout: int) -> None:
    """POST parameter updates to a camera. Raises VapixError on failure."""
    url = f"http://{ip}/axis-cgi/param.cgi"
    try:
        resp = requests.post(
            url,
            data={**params, "action": "update"},
            auth=auth,
            timeout=timeout,
        )
    except requests.exceptions.Timeout:
        raise VapixError(f"Connection timeout to {ip}")
    except requests.exceptions.ConnectionError as e:
        raise VapixError(f"Connection error to {ip}: {e}")
    except requests.exceptions.RequestException as e:
        raise VapixError(f"Request error to {ip}: {e}")
    if resp.status_code != 200:
        raise VapixError(f"SET params on {ip} failed: {resp.status_code} {resp.reason}")
    if resp.text.strip().startswith("#"):
        raise VapixError(f"SET params on {ip} rejected: {resp.text.strip()[:120]}")


def add_motion_window(ip: str, auth: HTTPDigestAuth, timeout: int, sensitivity: int) -> int:
    """Add a full-frame motion detection window via param.cgi action=add.

    Returns the window index X (MX) assigned by the camera, which equals the
    event-system window ID used in action rule conditions.
    Raises VapixError on failure.
    """
    url = f"http://{ip}/axis-cgi/param.cgi"
    try:
        resp = requests.post(
            url,
            data={
                "action": "add",
                "template": "motion",
                "group": "Motion",
                "Motion.M.Name": "full_frame",
                "Motion.M.ImageSource": "0",
                "Motion.M.Left": "0",
                "Motion.M.Right": "9999",
                "Motion.M.Top": "0",
                "Motion.M.Bottom": "9999",
                "Motion.M.WindowType": "include",
                "Motion.M.Sensitivity": str(sensitivity),
                "Motion.M.History": "90",
                "Motion.M.ObjectSize": "15",
            },
            auth=auth,
            timeout=timeout,
        )
    except requests.exceptions.Timeout:
        raise VapixError(f"Connection timeout to {ip}")
    except requests.exceptions.ConnectionError as e:
        raise VapixError(f"Connection error to {ip}: {e}")
    except requests.exceptions.RequestException as e:
        raise VapixError(f"Request error to {ip}: {e}")
    if resp.status_code != 200:
        raise VapixError(f"ADD motion window on {ip} failed: {resp.status_code} {resp.reason}")
    # Response format: "MX OK\n" where X is the assigned window index
    m = re.match(r"M(\d+)\s+OK", resp.text.strip())
    if not m:
        raise VapixError(f"ADD motion window on {ip}: unexpected response {resp.text.strip()[:60]!r}")
    return int(m.group(1))


@dataclass
class InstalledApplication:
    name: str
    nice_name: str
    status: str
    version: str = ""


def get_applications(ip: str, auth: HTTPDigestAuth, timeout: int) -> list[InstalledApplication]:
    """Return all applications (ACAPs) installed on the camera, incl. Status (e.g. Running/Stopped)."""
    url = f"http://{ip}/axis-cgi/applications/list.cgi"
    try:
        resp = requests.get(url, auth=auth, timeout=timeout)
    except requests.exceptions.Timeout:
        raise VapixError(f"Connection timeout to {ip}")
    except requests.exceptions.ConnectionError as e:
        raise VapixError(f"Connection error to {ip}: {e}")
    except requests.exceptions.RequestException as e:
        raise VapixError(f"Request error to {ip}: {e}")
    if resp.status_code != 200:
        raise VapixError(f"LIST applications on {ip} failed: {resp.status_code} {resp.reason}")
    apps = []
    for tag in re.findall(r"<application\s[^>]*/?>", resp.text):
        name = re.search(r'\bName="([^"]*)"', tag)
        nice_name = re.search(r'\bNiceName="([^"]*)"', tag)
        status = re.search(r'\bStatus="([^"]*)"', tag)
        version = re.search(r'\bVersion="([^"]*)"', tag)
        if name:
            apps.append(InstalledApplication(
                name=name.group(1),
                nice_name=nice_name.group(1) if nice_name else "",
                status=status.group(1) if status else "",
                version=version.group(1) if version else "",
            ))
    return apps


def upload_application(ip: str, auth: HTTPDigestAuth, timeout: int, eap_path: str) -> None:
    """Upload and install an .eap application package. Raises VapixError on failure.

    Endpoint/field name ("packfil") follow Axis's documented Application API but
    are not independently verified against a live camera by this tool — if an
    install fails unexpectedly, confirm both against the target unit first (see
    apidiscovery.cgi / AXIS_CAMERA_SETUP_MANUAL.md section 1).
    """
    url = f"http://{ip}/axis-cgi/applications/upload.cgi"
    try:
        with open(eap_path, "rb") as f:
            resp = requests.post(
                url,
                auth=auth,
                files={"packfil": (Path(eap_path).name, f, "application/octet-stream")},
                timeout=timeout,
            )
    except FileNotFoundError:
        raise VapixError(f"Application package not found: {eap_path}")
    except requests.exceptions.Timeout:
        raise VapixError(f"Connection timeout to {ip}")
    except requests.exceptions.ConnectionError as e:
        raise VapixError(f"Connection error to {ip}: {e}")
    except requests.exceptions.RequestException as e:
        raise VapixError(f"Request error to {ip}: {e}")
    if resp.status_code != 200:
        raise VapixError(f"UPLOAD application {eap_path} to {ip} failed: {resp.status_code} {resp.reason}")
    if "error" in resp.text.lower():
        raise VapixError(f"UPLOAD application {eap_path} to {ip} rejected: {resp.text.strip()[:200]}")


def start_application(ip: str, auth: HTTPDigestAuth, timeout: int, package: str) -> None:
    """Start an installed application by package name. Raises VapixError on failure."""
    url = f"http://{ip}/axis-cgi/applications/control.cgi"
    try:
        resp = requests.get(
            url,
            params={"action": "start", "package": package},
            auth=auth,
            timeout=timeout,
        )
    except requests.exceptions.Timeout:
        raise VapixError(f"Connection timeout to {ip}")
    except requests.exceptions.ConnectionError as e:
        raise VapixError(f"Connection error to {ip}: {e}")
    except requests.exceptions.RequestException as e:
        raise VapixError(f"Request error to {ip}: {e}")
    if resp.status_code != 200:
        raise VapixError(f"START application {package} on {ip} failed: {resp.status_code} {resp.reason}")
    if "error" in resp.text.lower():
        raise VapixError(f"START application {package} on {ip} rejected: {resp.text.strip()[:200]}")


@dataclass
class Vmd4Profile:
    uid: int
    name: str
    camera: int


def get_vmd4_profiles(ip: str, auth: HTTPDigestAuth, timeout: int) -> list[Vmd4Profile]:
    """GET the built-in VMD3/VMD4 app's own profile/window configuration.

    Read-only. VERIFIED on firmware 12.11.72 (real AXIS M3085-V, 192.168.1.72):
    the modern built-in "vmd" app does not use the legacy root.Motion param.cgi
    group at all (confirmed empty on that hardware — see
    AXIS_CAMERA_SETUP_MANUAL.md section 1-2), so this JSON control API is the
    only way to see whether a motion window/profile exists for it.
    """
    url = f"http://{ip}/local/vmd/control.cgi"
    try:
        resp = requests.post(
            url,
            json={"apiVersion": "1.4", "method": "getConfiguration"},
            auth=auth,
            timeout=timeout,
        )
    except requests.exceptions.Timeout:
        raise VapixError(f"Connection timeout to {ip}")
    except requests.exceptions.ConnectionError as e:
        raise VapixError(f"Connection error to {ip}: {e}")
    except requests.exceptions.RequestException as e:
        raise VapixError(f"Request error to {ip}: {e}")
    if resp.status_code != 200:
        raise VapixError(f"GET VMD4 configuration from {ip} failed: {resp.status_code} {resp.reason}")
    try:
        payload = resp.json()
    except ValueError:
        raise VapixError(f"GET VMD4 configuration from {ip}: response was not valid JSON")
    profiles = payload.get("data", {}).get("profiles", [])
    return [
        Vmd4Profile(uid=p.get("uid"), name=p.get("name", ""), camera=p.get("camera", 1))
        for p in profiles
    ]


def get_vmd4_configuration(ip: str, auth: HTTPDigestAuth, timeout: int) -> dict:
    """GET the built-in VMD3/VMD4 app's full raw configuration payload.

    Read-only. Returns the response's opaque "data" dict as-is (profiles,
    cameras, configurationStatus, filters, triggers, ...) rather than a typed
    model — the schema has fields this tool doesn't need to understand beyond
    round-tripping them unmodified through set_vmd4_configuration below (same
    "preserve what we don't touch" approach as get_vmd_app_config/
    set_vmd_app_config for the legacy app). See get_vmd4_profiles for a typed,
    read-only view of just uid/name/camera used for display purposes.
    """
    url = f"http://{ip}/local/vmd/control.cgi"
    try:
        resp = requests.post(
            url,
            json={"apiVersion": "1.4", "method": "getConfiguration"},
            auth=auth,
            timeout=timeout,
        )
    except requests.exceptions.Timeout:
        raise VapixError(f"Connection timeout to {ip}")
    except requests.exceptions.ConnectionError as e:
        raise VapixError(f"Connection error to {ip}: {e}")
    except requests.exceptions.RequestException as e:
        raise VapixError(f"Request error to {ip}: {e}")
    if resp.status_code != 200:
        raise VapixError(f"GET VMD4 configuration from {ip} failed: {resp.status_code} {resp.reason}")
    try:
        payload = resp.json()
    except ValueError:
        raise VapixError(f"GET VMD4 configuration from {ip}: response was not valid JSON")
    return payload.get("data", {})


def set_vmd4_configuration(ip: str, auth: HTTPDigestAuth, timeout: int, data: dict) -> None:
    """SET the built-in VMD3/VMD4 app's full configuration payload.

    `data` should be a (deep-copied, modified) dict previously obtained from
    get_vmd4_configuration — round-trip semantics, not a partial patch.

    VERIFIED end-to-end against a real AXIS M3085-V (192.168.1.72, firmware
    12.11.72, 2026-08-04): this IS Axis's own official, documented VMD4 JSON
    control API (unlike the legacy .eap's reverse-engineered vaconfig.cgi) —
    confirmed via getSupportedVersions/method="setConfiguration" being
    recognized (error 2003 "mandatory parameter missing", not 2005 "method
    not found"). One thing that ISN'T documented anywhere accessible and had
    to be found empirically: the request payload key is "params", NOT "data"
    — sending the payload under "data" returns a 200 with an empty
    response data and no error, silently doing nothing. Confirmed via a
    getConfiguration readback after each attempt (configurationStatus
    incremented and the expanded includeArea trigger persisted only with
    "params").
    """
    url = f"http://{ip}/local/vmd/control.cgi"
    try:
        resp = requests.post(
            url,
            json={"apiVersion": "1.4", "context": "", "method": "setConfiguration", "params": data},
            auth=auth,
            timeout=timeout,
        )
    except requests.exceptions.Timeout:
        raise VapixError(f"Connection timeout to {ip}")
    except requests.exceptions.ConnectionError as e:
        raise VapixError(f"Connection error to {ip}: {e}")
    except requests.exceptions.RequestException as e:
        raise VapixError(f"Request error to {ip}: {e}")
    if resp.status_code != 200:
        raise VapixError(f"SET VMD4 configuration on {ip} failed: {resp.status_code} {resp.reason}")
    try:
        payload = resp.json()
    except ValueError:
        raise VapixError(f"SET VMD4 configuration on {ip}: response was not valid JSON")
    if "error" in payload:
        raise VapixError(f"SET VMD4 configuration on {ip} rejected: {payload['error']}")


@dataclass
class VmdAppArea:
    name: str
    points: list[tuple[float, float]]


def get_vmd_app_config(ip: str, auth: HTTPDigestAuth, timeout: int, app_name: str) -> list[VmdAppArea]:
    """GET the legacy VMD .eap app's own polygon detection-area configuration.

    Read-only. This endpoint isn't documented anywhere findable — it was found
    by reading local/<app_name>/setup.shtml's own JavaScript (loadAppConfig(),
    var configCGI = "/axis-cgi/vaconfig.cgi") since the setup page itself is
    IE/ActiveX-only and can't be used directly to inspect config. (The page's
    <form> declares action="/sm/sm.srv" but that's a red herring — the actual
    save button calls uploadAppConfig() directly via JS, POSTing to configCGI
    — see set_vmd_app_config below, which uses and VERIFIES that write path.)

    VERIFIED on firmware 5.51.7.4 against 3 real AXIS M3005/P1204 units
    (192.168.1.57/.60/.79) running AXIS_Video_Motion_Detection_2_2_1.eap — all
    three returned an identical factory-default "Detection Area" polygon
    (roughly 60% width/height, centered) at areaid=0, matching
    reconciler._LEGACY_VMD_APP_MOTION_FILTER's hardcoded areaid="0". This is a
    genuinely separate configuration surface from root.Motion (which `cctv
    apply`'s reconciler manages, Story 3.1/3.3) — root.Motion's window/
    sensitivity numbers do not describe what this app actually detects on.
    """
    url = f"http://{ip}/axis-cgi/vaconfig.cgi"
    try:
        resp = requests.get(url, params={"action": "get", "name": app_name}, auth=auth, timeout=timeout)
    except requests.exceptions.Timeout:
        raise VapixError(f"Connection timeout to {ip}")
    except requests.exceptions.ConnectionError as e:
        raise VapixError(f"Connection error to {ip}: {e}")
    except requests.exceptions.RequestException as e:
        raise VapixError(f"Request error to {ip}: {e}")
    if resp.status_code != 200:
        raise VapixError(f"GET VMD app config from {ip} failed: {resp.status_code} {resp.reason}")
    areas = []
    for obj_match in re.finditer(r'<namedObject name="([^"]*)">(.*?)</namedObject>', resp.text, re.DOTALL):
        name = obj_match.group(1)
        points = [
            (float(x), float(y))
            for x, y in re.findall(r'<point x="([^"]*)" y="([^"]*)"\s*/>', obj_match.group(2))
        ]
        if points:
            areas.append(VmdAppArea(name=name, points=points))
    return areas


def set_vmd_app_config(ip: str, auth: HTTPDigestAuth, timeout: int, app_name: str, areas: list[VmdAppArea]) -> None:
    """SET the legacy VMD .eap app's own polygon detection-area configuration.

    Replaces ALL of the app's named objects and its single <rule>'s Include
    parameters with `areas` — everything else in the app's config (<scripts>,
    <events>, <moteConfig>) is preserved via surgical regex replacement on the
    freshly-GET'd document, not reconstructed from scratch, since those other
    sections' schemas aren't independently confirmed.

    VERIFIED end-to-end against a real AXIS M3005 (192.168.1.60, firmware
    5.51.7.4, 2026-08-04): GET current config, expand the factory-default
    "Detection Area" from its ~60% centered polygon to full-frame
    ((1,1),(1,-1),(-1,-1),(-1,1)), POST it back, GET again — the change
    persisted exactly as sent. Found by reading local/<app_name>/setup.shtml's
    own JS (uploadAppConfig()) since the setup page itself is IE/ActiveX-only.
    The POST body is NOT form-urlencoded — it's a raw
    "action=modify&name=<app>\\n<config>...</config>" string (literal
    ampersand in the first line, then the raw XML document on the next).

    Only handles Include-type areas (every area becomes "Include" — matches
    every camera's config observed so far, all single-area with no Exclude
    zones). Exclude-area support isn't implemented since none was ever seen.
    """
    url = f"http://{ip}/axis-cgi/vaconfig.cgi"
    try:
        get_resp = requests.get(url, params={"action": "get", "name": app_name}, auth=auth, timeout=timeout)
    except requests.exceptions.Timeout:
        raise VapixError(f"Connection timeout to {ip}")
    except requests.exceptions.ConnectionError as e:
        raise VapixError(f"Connection error to {ip}: {e}")
    except requests.exceptions.RequestException as e:
        raise VapixError(f"Request error to {ip}: {e}")
    if get_resp.status_code != 200:
        raise VapixError(f"GET VMD app config from {ip} failed: {get_resp.status_code} {get_resp.reason}")

    config_match = re.search(r"(<config\b.*?</config>)", get_resp.text, re.DOTALL)
    if not config_match:
        raise VapixError(f"GET VMD app config from {ip}: response did not contain a <config> element")
    config_xml = config_match.group(1)

    named_objects_xml = "<namedObjects>" + "".join(
        f'<namedObject name="{a.name}"><data knownTypeName="geometry.polygon"><polygon>'
        + "".join(f'<point x="{x:.2f}" y="{y:.2f}"/>' for x, y in a.points)
        + "</polygon></data></namedObject>"
        for a in areas
    ) + "</namedObjects>"
    new_config = re.sub(r"<namedObjects>.*?</namedObjects>", named_objects_xml, config_xml, count=1, flags=re.DOTALL)

    rule_params_xml = "".join(f'<parameter name="Include" value="{a.name}" />' for a in areas)
    new_config = re.sub(
        r"(<rule\b[^>]*>).*?(</rule>)",
        lambda m: m.group(1) + rule_params_xml + m.group(2),
        new_config, count=1, flags=re.DOTALL,
    )

    body = f"action=modify&name={app_name}\n{new_config}"
    try:
        post_resp = requests.post(url, data=body, auth=auth, timeout=timeout)
    except requests.exceptions.Timeout:
        raise VapixError(f"Connection timeout to {ip}")
    except requests.exceptions.ConnectionError as e:
        raise VapixError(f"Connection error to {ip}: {e}")
    except requests.exceptions.RequestException as e:
        raise VapixError(f"Request error to {ip}: {e}")
    if post_resp.status_code != 200:
        raise VapixError(f"SET VMD app config on {ip} failed: {post_resp.status_code} {post_resp.reason}")
    if 'result="error"' in post_resp.text:
        raise VapixError(f"SET VMD app config on {ip} rejected: {post_resp.text.strip()[:200]}")


def _parse_param_response(text: str) -> dict[str, str]:
    """Parse VAPIX param.cgi response body: 'root.Foo=bar\\n...' → {'root.Foo': 'bar', ...}"""
    result: dict[str, str] = {}
    for line in text.splitlines():
        if "=" in line:
            key, _, value = line.partition("=")
            result[key.strip()] = value.strip()
    return result


# ---------------------------------------------------------------------------
# Action1 SOAP helpers
# ---------------------------------------------------------------------------

_SOAP_NS = (
    'xmlns:soap="http://www.w3.org/2003/05/soap-envelope" '
    'xmlns:aa="http://www.axis.com/vapix/ws/action1" '
    'xmlns:wsnt="http://docs.oasis-open.org/wsn/b-2" '
    'xmlns:tns1="http://www.onvif.org/ver10/topics" '
    'xmlns:tnsaxis="http://www.axis.com/2009/event/topics"'
)
_SERVICES_URL = "http://{ip}/vapix/services"
_ACTION1_NS = "http://www.axis.com/vapix/ws/action1"


@dataclass
class ActionConfiguration:
    config_id: int
    name: str
    template_token: str
    parameters: dict[str, str] = field(default_factory=dict)


@dataclass
class ActionRule:
    rule_id: int
    name: str
    enabled: bool
    topic: str
    primary_action: int


def _soap_post(ip: str, auth: HTTPDigestAuth, timeout: int, soap_action: str, body: str) -> str:
    """POST a SOAP envelope to /vapix/services. Returns response text or raises VapixError."""
    envelope = (
        f'<?xml version="1.0" encoding="utf-8"?>'
        f'<soap:Envelope {_SOAP_NS}>'
        f'<soap:Body>{body}</soap:Body>'
        f'</soap:Envelope>'
    )
    url = _SERVICES_URL.format(ip=ip)
    try:
        resp = requests.post(
            url,
            headers={
                "Content-Type": "application/soap+xml; charset=utf-8",
                "SOAPAction": f'"{_ACTION1_NS}/{soap_action}"',
            },
            data=envelope,
            auth=auth,
            timeout=timeout,
        )
    except requests.exceptions.Timeout:
        raise VapixError(f"Connection timeout to {ip}")
    except requests.exceptions.ConnectionError as e:
        raise VapixError(f"Connection error to {ip}: {e}")
    except requests.exceptions.RequestException as e:
        raise VapixError(f"Request error to {ip}: {e}")
    if resp.status_code not in (200, 400):
        raise VapixError(f"SOAP {soap_action} on {ip} failed: {resp.status_code} {resp.reason}")
    if "<SOAP-ENV:Fault>" in resp.text or "<SOAP-ENV:Fault>" in resp.text:
        reason = re.search(r"<SOAP-ENV:Text[^>]*>([^<]+)</SOAP-ENV:Text>", resp.text)
        msg = reason.group(1) if reason else resp.text[resp.text.find("<SOAP-ENV:Body>"):][:200]
        raise VapixError(f"SOAP {soap_action} on {ip} fault: {msg}")
    return resp.text


def get_action_configurations(ip: str, auth: HTTPDigestAuth, timeout: int) -> list[ActionConfiguration]:
    """Return all action configurations on the camera."""
    text = _soap_post(ip, auth, timeout, "GetActionConfigurations", "<aa:GetActionConfigurations/>")
    configs = []
    for block in re.findall(r"<aa:ActionConfiguration>(.*?)</aa:ActionConfiguration>", text, re.DOTALL):
        cfg_id = re.search(r"<aa:ConfigurationID>(\d+)</aa:ConfigurationID>", block)
        name = re.search(r"<aa:Name>([^<]*)</aa:Name>", block)
        token = re.search(r"<aa:TemplateToken>([^<]+)</aa:TemplateToken>", block)
        params: dict[str, str] = {}
        for pm in re.finditer(r'<aa:Parameter Value="([^"]*)" Name="([^"]*)"', block):
            params[pm.group(2)] = pm.group(1)
        if cfg_id and token:
            configs.append(ActionConfiguration(
                config_id=int(cfg_id.group(1)),
                name=name.group(1) if name else "",
                template_token=token.group(1),
                parameters=params,
            ))
    return configs


def get_action_rules(ip: str, auth: HTTPDigestAuth, timeout: int) -> list[ActionRule]:
    """Return all action rules on the camera."""
    text = _soap_post(ip, auth, timeout, "GetActionRules", "<aa:GetActionRules/>")
    rules = []
    for block in re.findall(r"<aa:ActionRule>(.*?)</aa:ActionRule>", text, re.DOTALL):
        rule_id = re.search(r"<aa:RuleID>(\d+)</aa:RuleID>", block)
        name = re.search(r"<aa:Name>([^<]*)</aa:Name>", block)
        enabled = re.search(r"<aa:Enabled>(true|false)</aa:Enabled>", block)
        topic = re.search(r"<wsnt:TopicExpression[^>]*>([^<]+)</wsnt:TopicExpression>", block)
        primary = re.search(r"<aa:PrimaryAction>(\d+)</aa:PrimaryAction>", block)
        if rule_id and primary:
            rules.append(ActionRule(
                rule_id=int(rule_id.group(1)),
                name=name.group(1) if name else "",
                enabled=(enabled.group(1) == "true") if enabled else False,
                topic=topic.group(1) if topic else "",
                primary_action=int(primary.group(1)),
            ))
    return rules


def add_action_configuration(
    ip: str,
    auth: HTTPDigestAuth,
    timeout: int,
    name: str,
    template_token: str,
    parameters: dict[str, str],
) -> int:
    """Create an action configuration. Returns the new ConfigurationID."""
    params_xml = "".join(
        f'<aa:Parameter Name="{k}" Value="{v}"/>' for k, v in parameters.items()
    )
    body = (
        f"<aa:AddActionConfiguration>"
        f"<aa:NewActionConfiguration>"
        f"<aa:Name>{name}</aa:Name>"
        f"<aa:TemplateToken>{template_token}</aa:TemplateToken>"
        f"<aa:Parameters>{params_xml}</aa:Parameters>"
        f"</aa:NewActionConfiguration>"
        f"</aa:AddActionConfiguration>"
    )
    text = _soap_post(ip, auth, timeout, "AddActionConfiguration", body)
    cfg_id = re.search(r"<aa:ConfigurationID>(\d+)</aa:ConfigurationID>", text)
    if not cfg_id:
        raise VapixError(f"AddActionConfiguration on {ip}: no ConfigurationID in response")
    return int(cfg_id.group(1))


def add_action_rule(
    ip: str,
    auth: HTTPDigestAuth,
    timeout: int,
    name: str,
    topic: str,
    message_filter: Optional[str],
    primary_action: int,
) -> int:
    """Create an action rule. Returns the new RuleID."""
    msg_content = (
        f'<wsnt:MessageContent Dialect="http://www.onvif.org/ver10/tev/messageContentFilter/ItemFilter">'
        f"{message_filter}"
        f"</wsnt:MessageContent>"
    ) if message_filter else ""
    body = (
        f"<aa:AddActionRule>"
        f"<aa:NewActionRule>"
        f"<aa:Name>{name}</aa:Name>"
        f"<aa:Enabled>true</aa:Enabled>"
        f"<aa:Conditions>"
        f"<aa:Condition>"
        f'<wsnt:TopicExpression Dialect="http://docs.oasis-open.org/wsn/t-1/TopicExpression/Concrete">'
        f"{topic}"
        f"</wsnt:TopicExpression>"
        f"{msg_content}"
        f"</aa:Condition>"
        f"</aa:Conditions>"
        f"<aa:PrimaryAction>{primary_action}</aa:PrimaryAction>"
        f"</aa:NewActionRule>"
        f"</aa:AddActionRule>"
    )
    text = _soap_post(ip, auth, timeout, "AddActionRule", body)
    rule_id = re.search(r"<aa:RuleID>(\d+)</aa:RuleID>", text)
    if not rule_id:
        raise VapixError(f"AddActionRule on {ip}: no RuleID in response")
    return int(rule_id.group(1))


def remove_action_rule(ip: str, auth: HTTPDigestAuth, timeout: int, rule_id: int) -> None:
    """Delete an action rule by ID."""
    body = f"<aa:RemoveActionRule><aa:RuleID>{rule_id}</aa:RuleID></aa:RemoveActionRule>"
    _soap_post(ip, auth, timeout, "RemoveActionRule", body)


def remove_action_configuration(ip: str, auth: HTTPDigestAuth, timeout: int, config_id: int) -> None:
    """Delete an action configuration by ID."""
    body = (
        f"<aa:RemoveActionConfiguration>"
        f"<aa:ConfigurationID>{config_id}</aa:ConfigurationID>"
        f"</aa:RemoveActionConfiguration>"
    )
    _soap_post(ip, auth, timeout, "RemoveActionConfiguration", body)
