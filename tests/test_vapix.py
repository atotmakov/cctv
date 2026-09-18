from unittest.mock import MagicMock, patch

import pytest
import requests as req_lib
from requests.auth import HTTPDigestAuth

from cctv.vapix import (
    VapixError,
    get_network_shares,
    ConfiguredNetworkShare,
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
    get_applications,
    upload_application,
    start_application,
    stop_application,
    InstalledApplication,
    get_ntp_fallback_servers,
    set_ntp_fallback_servers,
    get_vmd4_profiles,
    Vmd4Profile,
    get_vmd4_configuration,
    set_vmd4_configuration,
    get_vmd_app_config,
    set_vmd_app_config,
    VmdAppArea,
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


# ---------------------------------------------------------------------------
# Application (ACAP) install helpers
# ---------------------------------------------------------------------------

APPLICATIONS_LIST_RESPONSE = """<reply result="ok">
 <application Name="vmd" NiceName="AXIS Video Motion Detection" Vendor="Axis Communications" Version="4.3-1" ApplicationID="12345" License="None" Status="Running" ConfigurationPage="local/vmd/config.html" VendorHomePage="http://www.axis.com"/>
 <application Name="objectanalytics" NiceName="AXIS Object Analytics" Vendor="Axis Communications" Version="1.2-3" ApplicationID="54321" License="None" Status="Stopped" ConfigurationPage="local/objectanalytics/config.html" VendorHomePage="http://www.axis.com"/>
</reply>"""


def test_get_applications_parses_response() -> None:
    mock_resp = MagicMock(status_code=200, text=APPLICATIONS_LIST_RESPONSE)
    with patch("cctv.vapix.requests.get", return_value=mock_resp) as mock_get:
        apps = get_applications(IP, AUTH, timeout=5)
    assert len(apps) == 2
    assert apps[0] == InstalledApplication(name="vmd", nice_name="AXIS Video Motion Detection", status="Running", version="4.3-1")
    assert apps[1] == InstalledApplication(name="objectanalytics", nice_name="AXIS Object Analytics", status="Stopped", version="1.2-3")
    mock_get.assert_called_once_with(
        f"http://{IP}/axis-cgi/applications/list.cgi",
        auth=AUTH,
        timeout=5,
    )


def test_get_applications_missing_version_defaults_empty() -> None:
    resp = '<reply result="ok"><application Name="vmd" NiceName="AXIS Video Motion Detection" Status="Running"/></reply>'
    mock_resp = MagicMock(status_code=200, text=resp)
    with patch("cctv.vapix.requests.get", return_value=mock_resp):
        apps = get_applications(IP, AUTH, timeout=5)
    assert apps[0].version == ""


def test_get_applications_empty() -> None:
    mock_resp = MagicMock(status_code=200, text='<reply result="ok"></reply>')
    with patch("cctv.vapix.requests.get", return_value=mock_resp):
        assert get_applications(IP, AUTH, timeout=5) == []


def test_get_applications_non_2xx() -> None:
    mock_resp = MagicMock(status_code=401, reason="Unauthorized")
    with patch("cctv.vapix.requests.get", return_value=mock_resp):
        with pytest.raises(VapixError, match="401"):
            get_applications(IP, AUTH, timeout=5)


def test_get_applications_timeout() -> None:
    with patch("cctv.vapix.requests.get", side_effect=req_lib.exceptions.Timeout):
        with pytest.raises(VapixError, match="timeout"):
            get_applications(IP, AUTH, timeout=5)


def test_upload_application_success(tmp_path) -> None:
    eap_file = tmp_path / "vmd_4.3-1.eap"
    eap_file.write_bytes(b"fake-eap-bytes")
    mock_resp = MagicMock(status_code=200, text="OK")
    with patch("cctv.vapix.requests.post", return_value=mock_resp) as mock_post:
        upload_application(IP, AUTH, timeout=5, eap_path=str(eap_file))
    mock_post.assert_called_once()
    call_kwargs = mock_post.call_args[1]
    assert call_kwargs["auth"] == AUTH
    assert call_kwargs["timeout"] == 5
    assert "packfil" in call_kwargs["files"]
    assert call_kwargs["files"]["packfil"][0] == "vmd_4.3-1.eap"


def test_upload_application_missing_file_raises() -> None:
    with pytest.raises(VapixError, match="not found"):
        upload_application(IP, AUTH, timeout=5, eap_path="/nonexistent/vmd.eap")


def test_upload_application_non_2xx_raises(tmp_path) -> None:
    eap_file = tmp_path / "vmd.eap"
    eap_file.write_bytes(b"fake-eap-bytes")
    mock_resp = MagicMock(status_code=400, reason="Bad Request")
    with patch("cctv.vapix.requests.post", return_value=mock_resp):
        with pytest.raises(VapixError, match="400"):
            upload_application(IP, AUTH, timeout=5, eap_path=str(eap_file))


def test_upload_application_error_body_raises(tmp_path) -> None:
    eap_file = tmp_path / "vmd.eap"
    eap_file.write_bytes(b"fake-eap-bytes")
    mock_resp = MagicMock(status_code=200, text="Error: incompatible architecture")
    with patch("cctv.vapix.requests.post", return_value=mock_resp):
        with pytest.raises(VapixError, match="rejected"):
            upload_application(IP, AUTH, timeout=5, eap_path=str(eap_file))


def test_start_application_success() -> None:
    mock_resp = MagicMock(status_code=200, text="OK")
    with patch("cctv.vapix.requests.get", return_value=mock_resp) as mock_get:
        start_application(IP, AUTH, timeout=5, package="vmd")
    mock_get.assert_called_once_with(
        f"http://{IP}/axis-cgi/applications/control.cgi",
        params={"action": "start", "package": "vmd"},
        auth=AUTH,
        timeout=5,
    )


def test_start_application_non_2xx_raises() -> None:
    mock_resp = MagicMock(status_code=400, reason="Bad Request")
    with patch("cctv.vapix.requests.get", return_value=mock_resp):
        with pytest.raises(VapixError, match="400"):
            start_application(IP, AUTH, timeout=5, package="vmd")


def test_start_application_error_body_raises() -> None:
    mock_resp = MagicMock(status_code=200, text="Error: no such package")
    with patch("cctv.vapix.requests.get", return_value=mock_resp):
        with pytest.raises(VapixError, match="rejected"):
            start_application(IP, AUTH, timeout=5, package="vmd")


# ---------------------------------------------------------------------------
# get_vmd4_profiles — built-in VMD3/VMD4 app's own JSON profile config
# ---------------------------------------------------------------------------

VMD4_CONFIG_RESPONSE = {
    "apiVersion": "1.4", "method": "getConfiguration", "context": "",
    "data": {
        "configurationStatus": 0,
        "profiles": [
            {"camera": 1, "filters": [], "triggers": [], "uid": 1, "name": "Profile 1"},
        ],
        "cameras": [{"id": 1, "rotation": 0, "active": True}],
    },
}


def test_get_vmd4_profiles_parses_response() -> None:
    mock_resp = MagicMock(status_code=200)
    mock_resp.json.return_value = VMD4_CONFIG_RESPONSE
    with patch("cctv.vapix.requests.post", return_value=mock_resp) as mock_post:
        profiles = get_vmd4_profiles(IP, AUTH, timeout=5)
    assert profiles == [Vmd4Profile(uid=1, name="Profile 1", camera=1)]
    mock_post.assert_called_once_with(
        f"http://{IP}/local/vmd/control.cgi",
        json={"apiVersion": "1.4", "method": "getConfiguration"},
        auth=AUTH,
        timeout=5,
    )


def test_get_vmd4_profiles_empty() -> None:
    mock_resp = MagicMock(status_code=200)
    mock_resp.json.return_value = {"data": {"profiles": []}}
    with patch("cctv.vapix.requests.post", return_value=mock_resp):
        assert get_vmd4_profiles(IP, AUTH, timeout=5) == []


def test_get_vmd4_profiles_non_2xx_raises() -> None:
    mock_resp = MagicMock(status_code=404, reason="Not Found")
    with patch("cctv.vapix.requests.post", return_value=mock_resp):
        with pytest.raises(VapixError, match="404"):
            get_vmd4_profiles(IP, AUTH, timeout=5)


def test_get_vmd4_profiles_invalid_json_raises() -> None:
    mock_resp = MagicMock(status_code=200)
    mock_resp.json.side_effect = ValueError("not json")
    with patch("cctv.vapix.requests.post", return_value=mock_resp):
        with pytest.raises(VapixError, match="not valid JSON"):
            get_vmd4_profiles(IP, AUTH, timeout=5)


def test_get_vmd4_profiles_timeout() -> None:
    with patch("cctv.vapix.requests.post", side_effect=req_lib.exceptions.Timeout):
        with pytest.raises(VapixError, match="timeout"):
            get_vmd4_profiles(IP, AUTH, timeout=5)


# ---------------------------------------------------------------------------
# get_vmd4_configuration / set_vmd4_configuration — official VMD4 JSON API
# ---------------------------------------------------------------------------


def test_get_vmd4_configuration_returns_raw_data() -> None:
    mock_resp = MagicMock(status_code=200)
    mock_resp.json.return_value = VMD4_CONFIG_RESPONSE
    with patch("cctv.vapix.requests.post", return_value=mock_resp):
        data = get_vmd4_configuration(IP, AUTH, timeout=5)
    assert data == VMD4_CONFIG_RESPONSE["data"]


def test_get_vmd4_configuration_non_2xx_raises() -> None:
    mock_resp = MagicMock(status_code=401, reason="Unauthorized")
    with patch("cctv.vapix.requests.post", return_value=mock_resp):
        with pytest.raises(VapixError, match="401"):
            get_vmd4_configuration(IP, AUTH, timeout=5)


def test_set_vmd4_configuration_uses_params_key_not_data() -> None:
    """VERIFIED empirically against a real AXIS M3085-V (192.168.1.72, 2026-08-04):
    sending the payload under 'data' silently no-ops (200, no error, nothing
    persists) — only 'params' actually applies the change."""
    mock_resp = MagicMock(status_code=200)
    mock_resp.json.return_value = {"apiVersion": "1.4", "method": "setConfiguration", "context": "", "data": {}}
    payload = {"profiles": []}
    with patch("cctv.vapix.requests.post", return_value=mock_resp) as mock_post:
        set_vmd4_configuration(IP, AUTH, timeout=5, data=payload)
    mock_post.assert_called_once_with(
        f"http://{IP}/local/vmd/control.cgi",
        json={"apiVersion": "1.4", "context": "", "method": "setConfiguration", "params": payload},
        auth=AUTH,
        timeout=5,
    )


def test_set_vmd4_configuration_error_response_raises() -> None:
    mock_resp = MagicMock(status_code=200)
    mock_resp.json.return_value = {"apiVersion": "1.4", "method": "setConfiguration", "context": "",
                                    "error": {"code": "2003", "message": "A mandatory parameter is missing"}}
    with patch("cctv.vapix.requests.post", return_value=mock_resp):
        with pytest.raises(VapixError, match="rejected"):
            set_vmd4_configuration(IP, AUTH, timeout=5, data={})


def test_set_vmd4_configuration_non_2xx_raises() -> None:
    mock_resp = MagicMock(status_code=500, reason="Internal Server Error")
    with patch("cctv.vapix.requests.post", return_value=mock_resp):
        with pytest.raises(VapixError, match="500"):
            set_vmd4_configuration(IP, AUTH, timeout=5, data={})


def test_set_vmd4_configuration_timeout() -> None:
    with patch("cctv.vapix.requests.post", side_effect=req_lib.exceptions.Timeout):
        with pytest.raises(VapixError, match="timeout"):
            set_vmd4_configuration(IP, AUTH, timeout=5, data={})


# ---------------------------------------------------------------------------
# get_vmd_app_config — legacy .eap app's own polygon area config
# ---------------------------------------------------------------------------

VMD_APP_CONFIG_RESPONSE = """<reply result="ok">
<config version="1.0">
<application name="VideoMotionDetection">
  <ruleEngine>
    <namedObjects>
      <namedObject name="Detection Area">
        <data knownTypeName="geometry.polygon">
          <polygon>
            <point x="0.60" y="0.60"/>
            <point x="0.60" y="-0.60"/>
            <point x="-0.60" y="-0.60"/>
            <point x="-0.60" y="0.60"/>
          </polygon>
        </data>
      </namedObject>
    </namedObjects>
    <rules>
      <rule name="detection_0" function="monitor_area">
        <parameter name="Include" value="Detection Area" />
      </rule>
    </rules>
    <events>
      <event name="motion">
        <attr key="areaid" nicename="Area ID" tag="source" value="0"/>
      </event>
    </events>
  </ruleEngine>
</application>
</config>
</reply>"""


def test_get_vmd_app_config_parses_response() -> None:
    mock_resp = MagicMock(status_code=200, text=VMD_APP_CONFIG_RESPONSE)
    with patch("cctv.vapix.requests.get", return_value=mock_resp) as mock_get:
        areas = get_vmd_app_config(IP, AUTH, timeout=5, app_name="VideoMotionDetection")
    assert areas == [VmdAppArea(name="Detection Area", points=[(0.6, 0.6), (0.6, -0.6), (-0.6, -0.6), (-0.6, 0.6)])]
    mock_get.assert_called_once_with(
        f"http://{IP}/axis-cgi/vaconfig.cgi",
        params={"action": "get", "name": "VideoMotionDetection"},
        auth=AUTH,
        timeout=5,
    )


def test_get_vmd_app_config_no_named_objects() -> None:
    mock_resp = MagicMock(status_code=200, text='<reply result="ok"><config version="1.0"/></reply>')
    with patch("cctv.vapix.requests.get", return_value=mock_resp):
        assert get_vmd_app_config(IP, AUTH, timeout=5, app_name="VideoMotionDetection") == []


def test_get_vmd_app_config_non_2xx_raises() -> None:
    mock_resp = MagicMock(status_code=401, reason="Unauthorized")
    with patch("cctv.vapix.requests.get", return_value=mock_resp):
        with pytest.raises(VapixError, match="401"):
            get_vmd_app_config(IP, AUTH, timeout=5, app_name="VideoMotionDetection")


def test_get_vmd_app_config_timeout() -> None:
    with patch("cctv.vapix.requests.get", side_effect=req_lib.exceptions.Timeout):
        with pytest.raises(VapixError, match="timeout"):
            get_vmd_app_config(IP, AUTH, timeout=5, app_name="VideoMotionDetection")


# ---------------------------------------------------------------------------
# set_vmd_app_config — legacy .eap app's own polygon area config (write)
# ---------------------------------------------------------------------------


def test_set_vmd_app_config_full_flow() -> None:
    """GET current config, surgically replace namedObjects + rule params, POST it
    back with the raw (non-form-encoded) action=modify body — VERIFIED against a
    real AXIS M3005 (192.168.1.60, 2026-08-04): this exact flow persisted."""
    get_resp = MagicMock(status_code=200, text=VMD_APP_CONFIG_RESPONSE)
    post_resp = MagicMock(status_code=200, text='<reply result="ok" />')
    new_area = [VmdAppArea(name="Detection Area", points=[(1.0, 1.0), (1.0, -1.0), (-1.0, -1.0), (-1.0, 1.0)])]

    with patch("cctv.vapix.requests.get", return_value=get_resp) as mock_get, \
         patch("cctv.vapix.requests.post", return_value=post_resp) as mock_post:
        set_vmd_app_config(IP, AUTH, timeout=5, app_name="VideoMotionDetection", areas=new_area)

    mock_get.assert_called_once_with(
        f"http://{IP}/axis-cgi/vaconfig.cgi",
        params={"action": "get", "name": "VideoMotionDetection"},
        auth=AUTH,
        timeout=5,
    )
    mock_post.assert_called_once()
    args, kwargs = mock_post.call_args
    assert args[0] == f"http://{IP}/axis-cgi/vaconfig.cgi"
    body = kwargs["data"]
    assert body.startswith("action=modify&name=VideoMotionDetection\n")
    assert '<point x="1.00" y="1.00"/>' in body
    assert '<point x="-1.00" y="-1.00"/>' in body
    assert 'name="Detection Area"' in body
    assert '<parameter name="Include" value="Detection Area"' in body
    # untouched sections must survive the surgical replacement
    assert 'key="areaid"' in body


def test_set_vmd_app_config_get_non_2xx_raises() -> None:
    mock_resp = MagicMock(status_code=401, reason="Unauthorized")
    with patch("cctv.vapix.requests.get", return_value=mock_resp):
        with pytest.raises(VapixError, match="401"):
            set_vmd_app_config(IP, AUTH, timeout=5, app_name="VideoMotionDetection", areas=[])


def test_set_vmd_app_config_get_missing_config_element_raises() -> None:
    mock_resp = MagicMock(status_code=200, text='<reply result="ok"></reply>')
    with patch("cctv.vapix.requests.get", return_value=mock_resp):
        with pytest.raises(VapixError, match="did not contain a <config>"):
            set_vmd_app_config(IP, AUTH, timeout=5, app_name="VideoMotionDetection", areas=[])


def test_set_vmd_app_config_post_non_2xx_raises() -> None:
    get_resp = MagicMock(status_code=200, text=VMD_APP_CONFIG_RESPONSE)
    post_resp = MagicMock(status_code=500, reason="Internal Server Error")
    with patch("cctv.vapix.requests.get", return_value=get_resp), \
         patch("cctv.vapix.requests.post", return_value=post_resp):
        with pytest.raises(VapixError, match="500"):
            set_vmd_app_config(IP, AUTH, timeout=5, app_name="VideoMotionDetection", areas=[])


def test_set_vmd_app_config_post_error_result_raises() -> None:
    get_resp = MagicMock(status_code=200, text=VMD_APP_CONFIG_RESPONSE)
    post_resp = MagicMock(status_code=200, text='<reply result="error">bad config</reply>')
    with patch("cctv.vapix.requests.get", return_value=get_resp), \
         patch("cctv.vapix.requests.post", return_value=post_resp):
        with pytest.raises(VapixError, match="rejected"):
            set_vmd_app_config(IP, AUTH, timeout=5, app_name="VideoMotionDetection", areas=[])


def test_set_vmd_app_config_timeout_on_post() -> None:
    get_resp = MagicMock(status_code=200, text=VMD_APP_CONFIG_RESPONSE)
    with patch("cctv.vapix.requests.get", return_value=get_resp), \
         patch("cctv.vapix.requests.post", side_effect=req_lib.exceptions.Timeout):
        with pytest.raises(VapixError, match="timeout"):
            set_vmd_app_config(IP, AUTH, timeout=5, app_name="VideoMotionDetection", areas=[])


# ---------------------------------------------------------------------------
# stop_application
# ---------------------------------------------------------------------------


def test_stop_application_success() -> None:
    mock_resp = MagicMock(status_code=200, text="OK")
    with patch("cctv.vapix.requests.get", return_value=mock_resp) as mock_get:
        stop_application(IP, AUTH, timeout=5, package="sds3sync")
    mock_get.assert_called_once_with(
        f"http://{IP}/axis-cgi/applications/control.cgi",
        params={"action": "stop", "package": "sds3sync"},
        auth=AUTH,
        timeout=5,
    )


def test_stop_application_non_2xx_raises() -> None:
    mock_resp = MagicMock(status_code=400, reason="Bad Request")
    with patch("cctv.vapix.requests.get", return_value=mock_resp):
        with pytest.raises(VapixError, match="400"):
            stop_application(IP, AUTH, timeout=5, package="sds3sync")


def test_stop_application_error_body_raises() -> None:
    mock_resp = MagicMock(status_code=200, text="Error: no such package")
    with patch("cctv.vapix.requests.get", return_value=mock_resp):
        with pytest.raises(VapixError, match="rejected"):
            stop_application(IP, AUTH, timeout=5, package="sds3sync")


def test_stop_application_timeout_raises() -> None:
    with patch("cctv.vapix.requests.get", side_effect=req_lib.exceptions.Timeout):
        with pytest.raises(VapixError, match="timeout"):
            stop_application(IP, AUTH, timeout=5, package="sds3sync")


# ---------------------------------------------------------------------------
# NTP fallback servers — modern /config/rest API
# ---------------------------------------------------------------------------

NTP_CLIENT_RESPONSE = {
    "status": "success",
    "data": {
        "staticServers": ["pool.ntp.org", "ntp1.vniiftri.ru"],
        "enabled": True,
        "serversSource": "DHCP",
        "synced": True,
    },
}


def test_get_ntp_fallback_servers_parses_static_servers() -> None:
    mock_resp = MagicMock(status_code=200)
    mock_resp.json.return_value = NTP_CLIENT_RESPONSE
    with patch("cctv.vapix.requests.get", return_value=mock_resp) as mock_get:
        servers = get_ntp_fallback_servers(IP, AUTH, timeout=5)

    assert servers == ["pool.ntp.org", "ntp1.vniiftri.ru"]
    mock_get.assert_called_once_with(
        f"http://{IP}/config/rest/network-time-sync/v1/ntp/client", auth=AUTH, timeout=5,
    )


def test_get_ntp_fallback_servers_empty_when_none_configured() -> None:
    mock_resp = MagicMock(status_code=200)
    mock_resp.json.return_value = {"status": "success", "data": {"enabled": True}}
    with patch("cctv.vapix.requests.get", return_value=mock_resp):
        assert get_ntp_fallback_servers(IP, AUTH, timeout=5) == []


def test_get_ntp_fallback_servers_non_2xx_raises() -> None:
    mock_resp = MagicMock(status_code=404, reason="Not Found")
    with patch("cctv.vapix.requests.get", return_value=mock_resp):
        with pytest.raises(VapixError, match="404"):
            get_ntp_fallback_servers(IP, AUTH, timeout=5)


def test_get_ntp_fallback_servers_non_json_raises() -> None:
    mock_resp = MagicMock(status_code=200)
    mock_resp.json.side_effect = ValueError
    with patch("cctv.vapix.requests.get", return_value=mock_resp):
        with pytest.raises(VapixError, match="not valid JSON"):
            get_ntp_fallback_servers(IP, AUTH, timeout=5)


def test_get_ntp_fallback_servers_error_status_raises() -> None:
    mock_resp = MagicMock(status_code=200)
    mock_resp.json.return_value = {"status": "error", "error": {"code": 12, "message": "nope"}}
    with patch("cctv.vapix.requests.get", return_value=mock_resp):
        with pytest.raises(VapixError, match="rejected"):
            get_ntp_fallback_servers(IP, AUTH, timeout=5)


def test_set_ntp_fallback_servers_posts_data_envelope() -> None:
    """The write body must mirror the GET response's `data` envelope — posting
    bare fields is rejected by the camera with "no 'data' field"."""
    mock_resp = MagicMock(status_code=200)
    mock_resp.json.return_value = {"status": "success"}
    with patch("cctv.vapix.requests.post", return_value=mock_resp) as mock_post:
        set_ntp_fallback_servers(IP, AUTH, 5, ["pool.ntp.org", "ntp1.vniiftri.ru"])

    mock_post.assert_called_once_with(
        f"http://{IP}/config/rest/network-time-sync/v1/ntp/client",
        json={"data": {"staticServers": ["pool.ntp.org", "ntp1.vniiftri.ru"]}},
        auth=AUTH,
        timeout=5,
    )


def test_set_ntp_fallback_servers_non_2xx_raises() -> None:
    mock_resp = MagicMock(status_code=500, reason="Internal Server Error")
    with patch("cctv.vapix.requests.post", return_value=mock_resp):
        with pytest.raises(VapixError, match="500"):
            set_ntp_fallback_servers(IP, AUTH, 5, ["pool.ntp.org"])


def test_set_ntp_fallback_servers_error_status_raises() -> None:
    mock_resp = MagicMock(status_code=200)
    mock_resp.json.return_value = {
        "status": "error",
        "error": {"code": 12, "message": "Invalid JSON body: There is no 'data' field"},
    }
    with patch("cctv.vapix.requests.post", return_value=mock_resp):
        with pytest.raises(VapixError, match="rejected"):
            set_ntp_fallback_servers(IP, AUTH, 5, ["pool.ntp.org"])


def test_set_ntp_fallback_servers_connection_error_raises() -> None:
    with patch("cctv.vapix.requests.post", side_effect=req_lib.exceptions.ConnectionError("refused")):
        with pytest.raises(VapixError, match="Connection error"):
            set_ntp_fallback_servers(IP, AUTH, 5, ["pool.ntp.org"])


# ---------------------------------------------------------------------------
# get_network_shares — the camera's own share API, which never exposes the
# internal root.NetworkShare.Nx index.
# ---------------------------------------------------------------------------

_SHARE_LIST_XML = """<?xml version="1.0" encoding="utf-8"?>
<NetworkShareResponse SchemaVersion="1.0">
  <ListSuccess>
    <NetworkShares NumberOfShares="1">
      <NetworkShare NiceName="cctv" ShareId="10991" Address="192.168.1.100" Share="cctv" User="cctv" DiskId="NetworkShare"/>
    </NetworkShares>
  </ListSuccess>
</NetworkShareResponse>"""


def test_get_network_shares_parses_response() -> None:
    """Share is reported identically regardless of which Nx slot backs it."""
    mock_resp = MagicMock(status_code=200, text=_SHARE_LIST_XML)
    with patch("cctv.vapix.requests.get", return_value=mock_resp) as mock_get:
        shares = get_network_shares(IP, AUTH, timeout=5)
    assert shares == [ConfiguredNetworkShare(
        share_id="10991", nice_name="cctv", address="192.168.1.100",
        share="cctv", user="cctv", disk_id="NetworkShare",
    )]
    mock_get.assert_called_once_with(
        f"http://{IP}/axis-cgi/disks/networkshare/list.cgi",
        params={"schemaversion": "1"},
        auth=AUTH,
        timeout=5,
    )


def test_get_network_shares_ignores_wrapper_element() -> None:
    """<NetworkShares NumberOfShares=..> wrapper must not be parsed as a share."""
    xml = '<NetworkShares NumberOfShares="0"></NetworkShares>'
    mock_resp = MagicMock(status_code=200, text=xml)
    with patch("cctv.vapix.requests.get", return_value=mock_resp):
        assert get_network_shares(IP, AUTH, timeout=5) == []


def test_get_network_shares_non_2xx_raises() -> None:
    mock_resp = MagicMock(status_code=401, reason="Unauthorized", text="")
    with patch("cctv.vapix.requests.get", return_value=mock_resp):
        with pytest.raises(VapixError, match="failed"):
            get_network_shares(IP, AUTH, timeout=5)


def test_get_network_shares_timeout_raises() -> None:
    with patch("cctv.vapix.requests.get", side_effect=req_lib.exceptions.Timeout):
        with pytest.raises(VapixError, match="timeout"):
            get_network_shares(IP, AUTH, timeout=5)
