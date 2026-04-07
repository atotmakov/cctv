from __future__ import annotations

import re
from dataclasses import dataclass, field
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
