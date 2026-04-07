from unittest.mock import MagicMock, patch

import pytest
import requests as req_lib
from requests.auth import HTTPDigestAuth

from cctv.vapix import (
    VapixError,
    _parse_param_response,
    get_params,
    set_params,
    add_motion_window,
    get_action_configurations,
    get_action_rules,
    add_action_configuration,
    add_action_rule,
    ActionConfiguration,
    ActionRule,
)

AUTH = HTTPDigestAuth("root", "testpass")
IP = "192.168.1.101"
BRAND_RESPONSE = (
    "root.Brand.Brand=AXIS\n"
    "root.Brand.ProdFullName=AXIS P3245-V\n"
    "root.Brand.ProdNbr=P3245-V\n"
)


# ---------------------------------------------------------------------------
# get_params
# ---------------------------------------------------------------------------


def test_get_params_success() -> None:
    mock_resp = MagicMock(status_code=200, text=BRAND_RESPONSE)
    with patch("cctv.vapix.requests.get", return_value=mock_resp) as mock_get:
        result = get_params(IP, "root.Brand", AUTH, timeout=5)
    assert result == {
        "root.Brand.Brand": "AXIS",
        "root.Brand.ProdFullName": "AXIS P3245-V",
        "root.Brand.ProdNbr": "P3245-V",
    }
    mock_get.assert_called_once_with(
        f"http://{IP}/axis-cgi/param.cgi",
        params={"action": "list", "group": "root.Brand"},
        auth=AUTH,
        timeout=5,
    )


def test_get_params_non_2xx() -> None:
    mock_resp = MagicMock(status_code=401, reason="Unauthorized")
    with patch("cctv.vapix.requests.get", return_value=mock_resp):
        with pytest.raises(VapixError, match="401"):
            get_params(IP, "root.Brand", AUTH, timeout=5)


def test_get_params_timeout() -> None:
    with patch("cctv.vapix.requests.get", side_effect=req_lib.exceptions.Timeout):
        with pytest.raises(VapixError, match="timeout"):
            get_params(IP, "root.Brand", AUTH, timeout=5)


def test_get_params_connection_error() -> None:
    with patch("cctv.vapix.requests.get", side_effect=req_lib.exceptions.ConnectionError("refused")):
        with pytest.raises(VapixError, match="Connection error"):
            get_params(IP, "root.Brand", AUTH, timeout=5)


def test_get_params_request_exception_fallback() -> None:
    with patch("cctv.vapix.requests.get", side_effect=req_lib.exceptions.TooManyRedirects):
        with pytest.raises(VapixError, match="Request error"):
            get_params(IP, "root.Brand", AUTH, timeout=5)


# ---------------------------------------------------------------------------
# set_params
# ---------------------------------------------------------------------------


def test_set_params_success() -> None:
    mock_resp = MagicMock(status_code=200, text="OK")
    with patch("cctv.vapix.requests.post", return_value=mock_resp) as mock_post:
        set_params(IP, {"root.Network.Share.Path": "/recordings"}, AUTH, timeout=5)
    mock_post.assert_called_once_with(
        f"http://{IP}/axis-cgi/param.cgi",
        data={"action": "update", "root.Network.Share.Path": "/recordings"},
        auth=AUTH,
        timeout=5,
    )


def test_set_params_non_2xx() -> None:
    mock_resp = MagicMock(status_code=400, reason="Bad Request")
    with patch("cctv.vapix.requests.post", return_value=mock_resp):
        with pytest.raises(VapixError, match="400"):
            set_params(IP, {"root.Network.Share.Path": "/recordings"}, AUTH, timeout=5)


def test_add_motion_window_returns_index() -> None:
    mock_resp = MagicMock(status_code=200, text="M1 OK\n")
    with patch("cctv.vapix.requests.post", return_value=mock_resp) as mock_post:
        idx = add_motion_window(IP, AUTH, timeout=5, sensitivity=50)
    assert idx == 1
    call_data = mock_post.call_args[1]["data"]
    assert call_data["action"] == "add"
    assert call_data["template"] == "motion"
    assert call_data["group"] == "Motion"
    assert call_data["Motion.M.Left"] == "0"
    assert call_data["Motion.M.Right"] == "9999"
    assert call_data["Motion.M.Sensitivity"] == "50"


def test_add_motion_window_m0() -> None:
    mock_resp = MagicMock(status_code=200, text="M0 OK\n")
    with patch("cctv.vapix.requests.post", return_value=mock_resp):
        idx = add_motion_window(IP, AUTH, timeout=5, sensitivity=80)
    assert idx == 0


def test_add_motion_window_non_2xx_raises() -> None:
    mock_resp = MagicMock(status_code=400, reason="Bad Request")
    with patch("cctv.vapix.requests.post", return_value=mock_resp):
        with pytest.raises(VapixError, match="400"):
            add_motion_window(IP, AUTH, timeout=5, sensitivity=50)


def test_add_motion_window_unexpected_body_raises() -> None:
    mock_resp = MagicMock(status_code=200, text="# Error: something went wrong")
    with patch("cctv.vapix.requests.post", return_value=mock_resp):
        with pytest.raises(VapixError, match="unexpected response"):
            add_motion_window(IP, AUTH, timeout=5, sensitivity=50)


def test_set_params_body_error_raises() -> None:
    """Camera returns HTTP 200 with '# Error: ...' body — must raise VapixError."""
    mock_resp = MagicMock(status_code=200, text="# Error: Error setting 'root.NetworkShare.N0.Address' to '1.2.3.4'!")
    with patch("cctv.vapix.requests.post", return_value=mock_resp):
        with pytest.raises(VapixError, match="rejected"):
            set_params(IP, {"root.NetworkShare.N0.Address": "1.2.3.4"}, AUTH, timeout=5)


def test_set_params_timeout() -> None:
    with patch("cctv.vapix.requests.post", side_effect=req_lib.exceptions.Timeout):
        with pytest.raises(VapixError, match="timeout"):
            set_params(IP, {"root.Network.Share.Path": "/recordings"}, AUTH, timeout=5)


def test_set_params_connection_error() -> None:
    with patch("cctv.vapix.requests.post", side_effect=req_lib.exceptions.ConnectionError("refused")):
        with pytest.raises(VapixError, match="Connection error"):
            set_params(IP, {"root.Network.Share.Path": "/recordings"}, AUTH, timeout=5)


def test_set_params_request_exception_fallback() -> None:
    with patch("cctv.vapix.requests.post", side_effect=req_lib.exceptions.TooManyRedirects):
        with pytest.raises(VapixError, match="Request error"):
            set_params(IP, {"root.Network.Share.Path": "/recordings"}, AUTH, timeout=5)


# ---------------------------------------------------------------------------
# _parse_param_response
# ---------------------------------------------------------------------------


def test_parse_param_response_typical() -> None:
    result = _parse_param_response(BRAND_RESPONSE)
    assert result == {
        "root.Brand.Brand": "AXIS",
        "root.Brand.ProdFullName": "AXIS P3245-V",
        "root.Brand.ProdNbr": "P3245-V",
    }


def test_parse_param_response_empty() -> None:
    assert _parse_param_response("") == {}


def test_parse_param_response_blank_lines() -> None:
    text = "\nroot.Brand.Brand=AXIS\n\n"
    assert _parse_param_response(text) == {"root.Brand.Brand": "AXIS"}


# ---------------------------------------------------------------------------
# Credential hygiene
# ---------------------------------------------------------------------------


def test_no_credentials_in_error_get() -> None:
    mock_resp = MagicMock(status_code=401, reason="Unauthorized")
    with patch("cctv.vapix.requests.get", return_value=mock_resp):
        with pytest.raises(VapixError) as exc_info:
            get_params(IP, "root.Brand", AUTH, timeout=5)
    assert "testpass" not in str(exc_info.value)


def test_no_credentials_in_error_set() -> None:
    mock_resp = MagicMock(status_code=401, reason="Unauthorized")
    with patch("cctv.vapix.requests.post", return_value=mock_resp):
        with pytest.raises(VapixError) as exc_info:
            set_params(IP, {"root.Foo": "bar"}, AUTH, timeout=5)
    assert "testpass" not in str(exc_info.value)


# ---------------------------------------------------------------------------
# SOAP Action1 helpers
# ---------------------------------------------------------------------------

GET_CONFIGS_RESPONSE = """<?xml version="1.0"?>
<SOAP-ENV:Envelope xmlns:SOAP-ENV="http://www.w3.org/2003/05/soap-envelope"
                   xmlns:aa="http://www.axis.com/vapix/ws/action1">
<SOAP-ENV:Body><aa:GetActionConfigurationsResponse><aa:ActionConfigurations>
  <aa:ActionConfiguration>
    <aa:ConfigurationID>2</aa:ConfigurationID>
    <aa:Name>cctv_motion_record</aa:Name>
    <aa:TemplateToken>com.axis.action.unlimited.recording.storage</aa:TemplateToken>
    <aa:Parameters>
      <aa:Parameter Value="5000" Name="post_duration"></aa:Parameter>
      <aa:Parameter Value="5000" Name="pre_duration"></aa:Parameter>
      <aa:Parameter Value="NetworkShare" Name="storage_id"></aa:Parameter>
      <aa:Parameter Value="" Name="stream_options"></aa:Parameter>
    </aa:Parameters>
  </aa:ActionConfiguration>
</aa:ActionConfigurations></aa:GetActionConfigurationsResponse></SOAP-ENV:Body>
</SOAP-ENV:Envelope>"""

GET_RULES_RESPONSE = """<?xml version="1.0"?>
<SOAP-ENV:Envelope xmlns:SOAP-ENV="http://www.w3.org/2003/05/soap-envelope"
                   xmlns:aa="http://www.axis.com/vapix/ws/action1"
                   xmlns:wsnt="http://docs.oasis-open.org/wsn/b-2">
<SOAP-ENV:Body><aa:GetActionRulesResponse><aa:ActionRules>
  <aa:ActionRule>
    <aa:RuleID>2</aa:RuleID>
    <aa:Name>cctv_motion_record</aa:Name>
    <aa:Enabled>true</aa:Enabled>
    <aa:Conditions>
      <aa:Condition>
        <wsnt:TopicExpression Dialect="http://docs.oasis-open.org/wsn/t-1/TopicExpression/Concrete">tns1:VideoAnalytics/tnsaxis:MotionDetection//.</wsnt:TopicExpression>
        <wsnt:MessageContent Dialect="http://www.onvif.org/ver10/tev/messageContentFilter/ItemFilter">boolean(//SimpleItem[@Name="motion" and @Value="1"])</wsnt:MessageContent>
      </aa:Condition>
    </aa:Conditions>
    <aa:PrimaryAction>2</aa:PrimaryAction>
  </aa:ActionRule>
</aa:ActionRules></aa:GetActionRulesResponse></SOAP-ENV:Body>
</SOAP-ENV:Envelope>"""

ADD_CONFIG_RESPONSE = """<?xml version="1.0"?>
<SOAP-ENV:Envelope xmlns:SOAP-ENV="http://www.w3.org/2003/05/soap-envelope"
                   xmlns:aa="http://www.axis.com/vapix/ws/action1">
<SOAP-ENV:Body><aa:AddActionConfigurationResponse>
  <aa:ConfigurationID>3</aa:ConfigurationID>
</aa:AddActionConfigurationResponse></SOAP-ENV:Body>
</SOAP-ENV:Envelope>"""

ADD_RULE_RESPONSE = """<?xml version="1.0"?>
<SOAP-ENV:Envelope xmlns:SOAP-ENV="http://www.w3.org/2003/05/soap-envelope"
                   xmlns:aa="http://www.axis.com/vapix/ws/action1">
<SOAP-ENV:Body><aa:AddActionRuleResponse>
  <aa:RuleID>3</aa:RuleID>
</aa:AddActionRuleResponse></SOAP-ENV:Body>
</SOAP-ENV:Envelope>"""

SOAP_FAULT_RESPONSE = """<?xml version="1.0"?>
<SOAP-ENV:Envelope xmlns:SOAP-ENV="http://www.w3.org/2003/05/soap-envelope">
<SOAP-ENV:Body><SOAP-ENV:Fault>
  <SOAP-ENV:Code><SOAP-ENV:Value>SOAP-ENV:Sender</SOAP-ENV:Value></SOAP-ENV:Code>
  <SOAP-ENV:Reason><SOAP-ENV:Text xml:lang="en">failed to parse topic expression</SOAP-ENV:Text></SOAP-ENV:Reason>
</SOAP-ENV:Fault></SOAP-ENV:Body>
</SOAP-ENV:Envelope>"""


def test_get_action_configurations_parses_response() -> None:
    mock_resp = MagicMock(status_code=200, text=GET_CONFIGS_RESPONSE)
    with patch("cctv.vapix.requests.post", return_value=mock_resp):
        configs = get_action_configurations(IP, AUTH, timeout=5)
    assert len(configs) == 1
    cfg = configs[0]
    assert cfg.config_id == 2
    assert cfg.name == "cctv_motion_record"
    assert cfg.template_token == "com.axis.action.unlimited.recording.storage"
    assert cfg.parameters["storage_id"] == "NetworkShare"
    assert cfg.parameters["post_duration"] == "5000"


def test_get_action_configurations_empty() -> None:
    empty = GET_CONFIGS_RESPONSE.replace(
        "<aa:ActionConfigurations>\n  <aa:ActionConfiguration>",
        "<aa:ActionConfigurations>",
    ).replace("  </aa:ActionConfiguration>\n</aa:ActionConfigurations>", "</aa:ActionConfigurations>")
    mock_resp = MagicMock(status_code=200, text=empty)
    with patch("cctv.vapix.requests.post", return_value=mock_resp):
        configs = get_action_configurations(IP, AUTH, timeout=5)
    assert configs == []


def test_get_action_rules_parses_response() -> None:
    mock_resp = MagicMock(status_code=200, text=GET_RULES_RESPONSE)
    with patch("cctv.vapix.requests.post", return_value=mock_resp):
        rules = get_action_rules(IP, AUTH, timeout=5)
    assert len(rules) == 1
    rule = rules[0]
    assert rule.rule_id == 2
    assert rule.name == "cctv_motion_record"
    assert rule.enabled is True
    assert "MotionDetection" in rule.topic
    assert rule.primary_action == 2


def test_get_action_rules_empty() -> None:
    empty_rules = GET_RULES_RESPONSE.replace(
        "\n  <aa:ActionRule>", ""
    ).replace("  </aa:ActionRule>\n", "")
    mock_resp = MagicMock(status_code=200, text=empty_rules)
    with patch("cctv.vapix.requests.post", return_value=mock_resp):
        rules = get_action_rules(IP, AUTH, timeout=5)
    assert rules == []


def test_add_action_configuration_returns_id() -> None:
    mock_resp = MagicMock(status_code=200, text=ADD_CONFIG_RESPONSE)
    with patch("cctv.vapix.requests.post", return_value=mock_resp):
        cfg_id = add_action_configuration(
            IP, AUTH, timeout=5,
            name="test",
            template_token="com.axis.action.unlimited.recording.storage",
            parameters={"storage_id": "NetworkShare", "post_duration": "5000"},
        )
    assert cfg_id == 3


def test_add_action_rule_returns_id() -> None:
    mock_resp = MagicMock(status_code=200, text=ADD_RULE_RESPONSE)
    with patch("cctv.vapix.requests.post", return_value=mock_resp):
        rule_id = add_action_rule(
            IP, AUTH, timeout=5,
            name="test",
            topic="tns1:VideoAnalytics/tnsaxis:MotionDetection",
            message_filter='boolean(//SimpleItem[@Name="motion" and @Value="1"])',
            primary_action=3,
        )
    assert rule_id == 3


def test_soap_fault_raises_vapix_error() -> None:
    mock_resp = MagicMock(status_code=400, text=SOAP_FAULT_RESPONSE)
    with patch("cctv.vapix.requests.post", return_value=mock_resp):
        with pytest.raises(VapixError, match="failed to parse topic"):
            add_action_rule(
                IP, AUTH, timeout=5,
                name="test",
                topic="bad:Topic",
                message_filter=None,
                primary_action=1,
            )


def test_soap_timeout_raises_vapix_error() -> None:
    with patch("cctv.vapix.requests.post", side_effect=req_lib.exceptions.Timeout):
        with pytest.raises(VapixError, match="timeout"):
            get_action_rules(IP, AUTH, timeout=5)


def test_soap_connection_error_raises_vapix_error() -> None:
    with patch("cctv.vapix.requests.post", side_effect=req_lib.exceptions.ConnectionError("refused")):
        with pytest.raises(VapixError, match="Connection error"):
            get_action_configurations(IP, AUTH, timeout=5)
