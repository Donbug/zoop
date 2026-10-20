"""`zoop-ai config-check`: offline, stateless, redacted. No test here opens a socket or sends a request."""
from __future__ import annotations

import json
import socket
import subprocess
import sys

import httpx
import pytest

from zoop_ai.doctor import build_report, render_text
from zoop_ai.provider import stage_config

STAGES = ("DOCUMENT_SUMMARY", "DOCUMENT_SENTIMENT", "VERIFY", "BRIEFING_OUTLOOK")
SECRET = "sk-SECRETVALUE-do-not-print-0123456789"
PROXY_SECRET = "proxy-user:proxy-pass-SECRET"
NAMES = ["ZOOP_AI_PROVIDER", "ZOOP_AI_VERIFY_PROVIDER", "ZOOP_AI_BASE_URL", "ZOOP_AI_API_KEY", "ZOOP_AI_LIVE_ENABLED", "ZOOP_AI_GLOBAL_MAX_CALLS",
         "OPENAI_API_KEY", "TYPESAFE_API_KEY", "TYPESAFE_BASE_URL", "TYPESAFE_VALIDATION_MODEL", "SSL_CERT_FILE", "SSL_CERT_DIR",
         "HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "NO_PROXY", "http_proxy", "https_proxy", "all_proxy", "no_proxy",
         *[f"ZOOP_AI_{s}_{f}" for s in STAGES for f in ("MODEL", "REASONING_EFFORT")]]


def string_leaves(value):
    """Parsed string values (keys included), so JSON quoting of other valid stages cannot masquerade as a leak."""
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for key, item in value.items():
            yield key
            yield from string_leaves(item)
    elif isinstance(value, list):
        for item in value:
            yield from string_leaves(item)


@pytest.fixture(autouse=True)
def clean_env(monkeypatch):
    for name in NAMES:
        monkeypatch.delenv(name, raising=False)


def luna(monkeypatch, effort="low"):
    for stage in STAGES:
        monkeypatch.setenv(f"ZOOP_AI_{stage}_MODEL", "gpt-6-luna")
        if effort:
            monkeypatch.setenv(f"ZOOP_AI_{stage}_REASONING_EFFORT", effort)
    monkeypatch.setenv("ZOOP_AI_LIVE_ENABLED", "1")
    monkeypatch.setenv("ZOOP_AI_GLOBAL_MAX_CALLS", "4")
    monkeypatch.setenv("ZOOP_AI_API_KEY", SECRET)


def codes(report, severity=None):
    return {(i["field"], i["code"]) for i in report["issues"] if severity in (None, i["severity"])}


def test_default_environment_is_valid_but_live_is_closed_and_spend_is_never_inferred():
    report = build_report()
    assert report["configValid"] is True and report["liveEnvironmentReady"] is False
    blockers = codes(report, "blocker")
    assert {("ZOOP_AI_LIVE_ENABLED", "live_not_enabled"), ("ZOOP_AI_GLOBAL_MAX_CALLS", "global_max_calls_not_positive"),
            ("ZOOP_AI_API_KEY", "api_key_required")} <= blockers
    assert {("ZOOP_AI_%s_MODEL" % s, "stage_model_required") for s in STAGES} <= blockers
    assert report["liveGate"] == {"enabledFlag": False, "globalMaxCalls": 0, "ceilingPositive": False, "apiKeyPresent": False,
                                  "typesafeApiKeyPresent": False}
    assert report["authorization"] == {"liveSpend": "not_inferred_from_environment",
                                       "accountAndModelAvailability": "unverified_no_request_sent"}
    assert report["budget"]["costCap"] is None and report["budget"]["unit"] == "calls"
    assert report["offline"] == {"networkRequests": 0, "stateAccess": "none", "grantsRead": False, "providerConstructed": False}


def test_valid_luna_configuration_is_ready_without_claiming_authorization_or_availability(monkeypatch):
    luna(monkeypatch)
    monkeypatch.setenv("ZOOP_AI_VERIFY_REASONING_EFFORT", "none")
    report = build_report()
    assert report["configValid"] and report["liveEnvironmentReady"]
    assert report["issues"] == []
    assert [s["status"] for s in report["stages"]] == ["ready"] * 4
    assert all(s["model"] == "gpt-6-luna" and s["reviewedModel"] for s in report["stages"])
    assert {s["kind"]: s["reasoningEffort"] for s in report["stages"]}["semantic-verification"] == "none"
    assert report["endpoint"]["providerRevision"] == stage_config("document-summary", "live").provider_revision
    assert report["authorization"]["liveSpend"] == "not_inferred_from_environment"
    assert report["liveGate"]["apiKeyPresent"] is True
    assert report["capabilities"]["nativeJev"] == {"adapter": True, "scope": "semantic-verification", "api": "POST /v1/systemone",
                                                   "model": "jev-1.14.0", "selected": False, "thresholds": "provisional_uncalibrated"}
    assert report["capabilities"]["s2"]["mode"] == report["capabilities"]["s3"]["mode"] == "replay_only"
    assert report["capabilities"]["s1"]["toolCalling"] is False
    assert report["productionProfile"]["status"] == "not_available"
    assert {g["code"] for g in report["capabilityGaps"]} >= {"responses_api_not_implemented", "native_jev_thresholds_uncalibrated"}


def test_luna_rejects_minimal_but_the_global_effort_enum_is_not_trimmed(monkeypatch):
    luna(monkeypatch, effort="minimal")
    report = build_report()
    assert not report["configValid"]
    assert ("ZOOP_AI_DOCUMENT_SUMMARY_REASONING_EFFORT", "reasoning_effort_unsupported_for_model") in codes(report, "error")
    # The worker itself still accepts minimal for any other model; only an unreviewed model warning is raised.
    for stage in STAGES:
        monkeypatch.setenv(f"ZOOP_AI_{stage}_MODEL", "some-other-model")
    other = build_report()
    assert other["configValid"] and ("ZOOP_AI_VERIFY_MODEL", "stage_model_not_in_reviewed_list") in codes(other, "warning")


def test_unset_effort_is_flagged_and_invalid_effort_reuses_stage_config_without_echo(monkeypatch):
    luna(monkeypatch, effort=None)
    assert ("ZOOP_AI_VERIFY_REASONING_EFFORT", "reasoning_effort_unset_provider_default_applies") in codes(build_report(), "warning")
    monkeypatch.setenv("ZOOP_AI_VERIFY_REASONING_EFFORT", "turbo-LEAK")
    report = build_report()
    assert ("ZOOP_AI_VERIFY_REASONING_EFFORT", "reasoning_effort_invalid") in codes(report, "error")
    assert "turbo-LEAK" not in json.dumps(report) + render_text(report)


@pytest.mark.parametrize("model", ["gpt 6 luna", '"gpt-6-luna"', SECRET, "x" * 200, "gpt-6-luna\nINJECT"])
def test_malformed_model_is_reported_by_field_and_never_echoed(monkeypatch, model):
    luna(monkeypatch)
    monkeypatch.setenv("ZOOP_AI_DOCUMENT_SUMMARY_MODEL", model)
    report = build_report()
    assert ("ZOOP_AI_DOCUMENT_SUMMARY_MODEL", "stage_model_malformed") in codes(report, "error")
    stage = report["stages"][0]
    assert stage["model"] is None and stage["modelState"] == "malformed" and stage["status"] == "invalid"
    leaves = list(string_leaves(report))
    assert not any(model.strip() in leaf for leaf in leaves)
    assert model.strip() not in render_text(report)


def test_native_jev_model_on_the_chat_adapter_and_typesafe_endpoint_fail_the_profile(monkeypatch):
    luna(monkeypatch)
    monkeypatch.setenv("ZOOP_AI_VERIFY_MODEL", "jev-1.14.0")
    monkeypatch.setenv("ZOOP_AI_BASE_URL", "https://api.typesafe.ai/v1")
    report = build_report()
    assert not report["configValid"] and not report["liveEnvironmentReady"]
    assert ("ZOOP_AI_VERIFY_MODEL", "native_jev_model_on_openai_compatible_chat") in codes(report, "error")
    assert ("ZOOP_AI_BASE_URL", "native_jev_endpoint_not_openai_compatible") in codes(report, "error")
    assert report["capabilities"]["nativeJev"]["selected"] is False
    monkeypatch.setenv("ZOOP_AI_BASE_URL", "https://example.test/v1/systemone")
    assert ("ZOOP_AI_BASE_URL", "native_jev_endpoint_not_openai_compatible") in codes(build_report(), "error")


JEV_SECRET = "ts-SECRETJEVKEY-do-not-print-0123456789"


def native(monkeypatch):
    """gpt-6-luna for generation and outlook, native Jev for verification: the chat verify settings must be gone."""
    luna(monkeypatch)
    monkeypatch.delenv("ZOOP_AI_VERIFY_MODEL")
    monkeypatch.delenv("ZOOP_AI_VERIFY_REASONING_EFFORT")
    monkeypatch.setenv("ZOOP_AI_VERIFY_PROVIDER", "typesafe-native")
    monkeypatch.setenv("TYPESAFE_VALIDATION_MODEL", "jev-1.14.0")
    monkeypatch.setenv("TYPESAFE_API_KEY", JEV_SECRET)


def verify_stage(report):
    return next(s for s in report["stages"] if s["kind"] == "semantic-verification")


def test_native_profile_is_ready_and_reports_the_native_recipient_revision_without_any_key(monkeypatch):
    native(monkeypatch)
    report = build_report("native-jev")
    assert report["configValid"] and report["liveEnvironmentReady"] and report["issues"] == []
    stage = verify_stage(report)
    assert (stage["provider"], stage["model"], stage["status"]) == ("typesafe-native", "jev-1.14.0", "ready")
    assert stage["reasoningEffort"] is None and stage["reasoningEffortState"] == "not_applicable"
    assert stage["env"] == {"model": "TYPESAFE_VALIDATION_MODEL", "reasoningEffort": None}
    assert {s["provider"] for s in report["stages"] if s is not stage} == {"openai-compatible"}
    assert report["verifyProvider"] == {"name": "typesafe-native", "supported": True, "selectedBy": "ZOOP_AI_VERIFY_PROVIDER"}
    native_revision = stage_config("semantic-verification", "live").provider_revision
    assert report["nativeEndpoint"]["providerRevision"] == native_revision
    assert report["endpoint"]["providerRevision"] == stage_config("document-summary", "live").provider_revision != native_revision
    assert report["nativeEndpoint"]["host"] == "api.typesafe.ai" and report["nativeEndpoint"]["defaultTypesafeHost"] is True
    assert report["liveGate"]["apiKeyPresent"] and report["liveGate"]["typesafeApiKeyPresent"]
    assert report["capabilities"]["nativeJev"]["selected"] is True
    assert "native_jev_thresholds_uncalibrated" in {g["code"] for g in report["capabilityGaps"]}
    shown = json.dumps(report) + render_text(report)
    assert JEV_SECRET not in shown and SECRET not in shown and "typesafeApiKeyPresent=True" in render_text(report)


def test_native_profile_blockers_errors_and_masking(monkeypatch):
    native(monkeypatch)
    monkeypatch.delenv("TYPESAFE_API_KEY")
    missing = build_report("native-jev")
    assert missing["configValid"] and not missing["liveEnvironmentReady"]
    assert ("TYPESAFE_API_KEY", "typesafe_api_key_required") in codes(missing, "blocker")
    monkeypatch.setenv("TYPESAFE_API_KEY", "ts-bad\nnewline-JEVLEAK")
    bad = build_report("native-jev")
    assert ("TYPESAFE_API_KEY", "typesafe_api_key_malformed") in codes(bad, "error") and "JEVLEAK" not in json.dumps(bad)
    monkeypatch.setenv("TYPESAFE_API_KEY", JEV_SECRET)
    monkeypatch.delenv("TYPESAFE_VALIDATION_MODEL")
    unset = build_report("native-jev")
    assert unset["configValid"] and ("TYPESAFE_VALIDATION_MODEL", "stage_model_required") in codes(unset, "blocker")
    for alias in ("jev-latest", "jev-preview", "jev-1.13.0"):
        monkeypatch.setenv("TYPESAFE_VALIDATION_MODEL", alias)
        report = build_report("native-jev")
        assert not report["configValid"] and ("TYPESAFE_VALIDATION_MODEL", "native_model_unsupported") in codes(report, "error")
        assert verify_stage(report)["status"] == "invalid"
    monkeypatch.setenv("TYPESAFE_VALIDATION_MODEL", SECRET)
    secret_like = build_report("native-jev")
    assert ("TYPESAFE_VALIDATION_MODEL", "stage_model_malformed") in codes(secret_like, "error")
    assert verify_stage(secret_like)["model"] is None and SECRET not in json.dumps(secret_like) + render_text(secret_like)


def test_stale_chat_verify_settings_are_errors_by_name_and_never_echoed(monkeypatch):
    native(monkeypatch)
    monkeypatch.setenv("ZOOP_AI_VERIFY_MODEL", "STALE-MODEL-LEAK")
    monkeypatch.setenv("ZOOP_AI_VERIFY_REASONING_EFFORT", "STALE-EFFORT-LEAK")
    report = build_report("native-jev")
    assert {("ZOOP_AI_VERIFY_MODEL", "native_verify_stale_model_setting"),
            ("ZOOP_AI_VERIFY_REASONING_EFFORT", "native_verify_stale_effort_setting")} <= codes(report, "error")
    assert not report["configValid"] and "LEAK" not in json.dumps(report) + render_text(report)


def test_each_profile_states_the_expected_route_and_a_mismatch_is_an_error_not_a_switch(monkeypatch):
    native(monkeypatch)
    default = build_report()
    assert not default["configValid"] and ("ZOOP_AI_VERIFY_PROVIDER", "native_verify_selected_use_native_jev_profile") in codes(default, "error")
    luna(monkeypatch)
    monkeypatch.delenv("ZOOP_AI_VERIFY_PROVIDER")
    chat = build_report("native-jev")
    assert not chat["configValid"] and ("ZOOP_AI_VERIFY_PROVIDER", "native_verify_not_selected") in codes(chat, "error")
    assert verify_stage(chat)["provider"] == "openai-compatible"


def test_an_unsupported_verify_provider_is_attributed_to_its_own_field(monkeypatch):
    luna(monkeypatch)
    monkeypatch.setenv("ZOOP_AI_VERIFY_PROVIDER", "typesafe-jev")
    for profile in ("s1-openai-compatible", "native-jev"):
        report = build_report(profile)
        assert ("ZOOP_AI_VERIFY_PROVIDER", "provider_unsupported") in codes(report, "error")
        assert ("ZOOP_AI_PROVIDER", "provider_unsupported") not in codes(report) and report["verifyProvider"]["supported"] is False


def test_typesafe_env_without_native_selection_is_only_a_warning(monkeypatch):
    luna(monkeypatch)
    monkeypatch.setenv("TYPESAFE_API_KEY", JEV_SECRET)
    report = build_report()
    assert report["configValid"] and report["nativeEndpoint"] is None
    assert ("TYPESAFE_API_KEY", "typesafe_env_present_native_verify_not_selected") in codes(report, "warning")
    assert JEV_SECRET not in json.dumps(report) + render_text(report)


@pytest.mark.parametrize("url,code", [
    ("http://api.example.test/v1", "provider_requires_https"),
    ("https://user:PASSWORD-LEAK@api.typesafe.ai/v1", "base_url_userinfo_forbidden"),
    ("https://api.typesafe.ai/v1?api_key=QUERY-LEAK", "base_url_query_or_fragment_forbidden"),
    ("https://api.typesafe.ai/v1/systemone", "native_base_url_includes_endpoint_path"),
    ("https://exa mple.test\nLEAK/v1", "base_url_malformed"),
])
def test_unsafe_native_endpoint_is_an_error_without_echoing_the_value(monkeypatch, url, code):
    native(monkeypatch)
    monkeypatch.setenv("TYPESAFE_BASE_URL", url)
    report = build_report("native-jev")
    assert ("TYPESAFE_BASE_URL", code) in codes(report, "error") and not report["configValid"]
    assert "providerRevision" not in report["nativeEndpoint"]
    shown = json.dumps(report) + render_text(report)
    for leak in ("PASSWORD-LEAK", "QUERY-LEAK", "LEAK/v1"):
        assert leak not in shown


def test_loopback_native_endpoint_is_valid_with_warnings_and_the_chat_endpoint_still_rejects_a_typesafe_host(monkeypatch):
    native(monkeypatch)
    monkeypatch.setenv("TYPESAFE_BASE_URL", "http://127.0.0.1:9/v1")
    report = build_report("native-jev")
    assert report["configValid"]
    assert {("TYPESAFE_BASE_URL", "endpoint_loopback_plain_http"), ("TYPESAFE_BASE_URL", "endpoint_not_default_typesafe_host")} <= codes(report, "warning")
    monkeypatch.setenv("TYPESAFE_BASE_URL", "https://api.typesafe.ai/v1")
    monkeypatch.setenv("ZOOP_AI_BASE_URL", "https://api.typesafe.ai/v1")
    assert ("ZOOP_AI_BASE_URL", "native_jev_endpoint_not_openai_compatible") in codes(build_report("native-jev"), "error")


def test_native_report_opens_no_socket_and_constructs_no_http_client(monkeypatch):
    native(monkeypatch)

    def refuse(*args, **kwargs):
        raise AssertionError("config-check must stay offline")

    monkeypatch.setattr(socket.socket, "connect", refuse)
    monkeypatch.setattr(socket, "getaddrinfo", refuse)
    monkeypatch.setattr(httpx.Client, "__init__", refuse)
    assert build_report("native-jev")["liveEnvironmentReady"]


@pytest.mark.parametrize("url,code", [
    ("http://api.example.test/v1", "provider_requires_https"),
    ("ftp://api.example.test/v1", "provider_requires_https"),
    ("", "provider_requires_https"),
    ("https://user:PASSWORD-LEAK@api.openai.com/v1", "base_url_userinfo_forbidden"),
    ("https://api.openai.com/v1?api_key=QUERY-LEAK", "base_url_query_or_fragment_forbidden"),
    ("https://api.openai.com/v1#FRAGMENT-LEAK", "base_url_query_or_fragment_forbidden"),
    ("https://exa mple.test\nLEAK/v1", "base_url_malformed"),
])
def test_unsafe_or_malformed_endpoint_is_an_error_without_echoing_the_value(monkeypatch, url, code):
    luna(monkeypatch)
    monkeypatch.setenv("ZOOP_AI_BASE_URL", url)
    report = build_report()
    assert ("ZOOP_AI_BASE_URL", code) in codes(report, "error")
    assert not report["configValid"] and "providerRevision" not in report["endpoint"]
    dumped = json.dumps(report) + render_text(report)
    for leak in ("PASSWORD-LEAK", "QUERY-LEAK", "FRAGMENT-LEAK", "LEAK/v1"):
        assert leak not in dumped


def test_loopback_http_and_custom_hosts_are_valid_with_warnings(monkeypatch):
    luna(monkeypatch)
    monkeypatch.setenv("ZOOP_AI_BASE_URL", "http://127.0.0.1:9/v1")
    report = build_report()
    assert report["configValid"]
    assert {("ZOOP_AI_BASE_URL", "endpoint_loopback_plain_http"), ("ZOOP_AI_BASE_URL", "endpoint_not_default_openai_host")} <= codes(report, "warning")


def test_proxy_environment_exposure_is_warned_by_name_only(monkeypatch):
    luna(monkeypatch)
    monkeypatch.setenv("HTTPS_PROXY", f"http://{PROXY_SECRET}@proxy.example.test:8080")
    report = build_report()
    assert report["configValid"]
    assert ("HTTPS_PROXY", "proxy_env_routes_endpoint") in codes(report, "warning")
    assert report["endpoint"]["proxy"]["routesEndpoint"] is True
    assert PROXY_SECRET not in json.dumps(report) + render_text(report)
    monkeypatch.setenv("NO_PROXY", "api.openai.com")
    assert report["endpoint"]["proxy"]["routesEndpoint"] and not build_report()["endpoint"]["proxy"]["routesEndpoint"]
    monkeypatch.setenv("SSL_CERT_FILE", "/tmp/custom-ca.pem")
    assert ("SSL_CERT_FILE", "custom_ca_env_present") in codes(build_report(), "warning")


def test_key_is_a_presence_boolean_only_and_malformed_or_misnamed_keys_are_flagged(monkeypatch):
    luna(monkeypatch)
    report = build_report()
    assert SECRET not in json.dumps(report) + render_text(report)
    monkeypatch.setenv("ZOOP_AI_API_KEY", "sk-bad\nnewline-SECRET")
    bad = build_report()
    assert ("ZOOP_AI_API_KEY", "api_key_malformed") in codes(bad, "error") and "newline-SECRET" not in json.dumps(bad)
    monkeypatch.delenv("ZOOP_AI_API_KEY")
    monkeypatch.setenv("OPENAI_API_KEY", SECRET)
    missing = build_report()
    assert ("ZOOP_AI_API_KEY", "api_key_required") in codes(missing, "blocker")
    assert ("OPENAI_API_KEY", "openai_api_key_env_not_read_use_zoop_ai_api_key") in codes(missing, "warning")
    assert SECRET not in json.dumps(missing)


@pytest.mark.parametrize("raw", ["abc", "", "1.5"])
def test_global_max_calls_is_parsed_exactly_like_the_cli_and_an_invalid_value_is_an_error(monkeypatch, raw):
    luna(monkeypatch)
    monkeypatch.setenv("ZOOP_AI_GLOBAL_MAX_CALLS", raw)
    report = build_report()
    assert ("ZOOP_AI_GLOBAL_MAX_CALLS", "global_max_calls_invalid") in codes(report, "error")
    assert report["liveGate"]["globalMaxCalls"] is None and not report["configValid"]


def test_only_exact_one_opens_the_live_gate_and_other_values_are_warned(monkeypatch):
    luna(monkeypatch)
    monkeypatch.setenv("ZOOP_AI_LIVE_ENABLED", "true")
    report = build_report()
    assert report["configValid"] and not report["liveEnvironmentReady"]
    assert ("ZOOP_AI_LIVE_ENABLED", "live_not_enabled") in codes(report, "blocker")
    assert ("ZOOP_AI_LIVE_ENABLED", "live_enabled_value_ignored_only_1_enables") in codes(report, "warning")


def test_unsupported_provider_is_an_error(monkeypatch):
    luna(monkeypatch)
    monkeypatch.setenv("ZOOP_AI_PROVIDER", "typesafe-jev")
    report = build_report()
    assert ("ZOOP_AI_PROVIDER", "provider_unsupported") in codes(report, "error") and report["provider"]["supported"] is False


def test_building_the_report_opens_no_socket_and_constructs_no_http_client(monkeypatch):
    luna(monkeypatch)

    def refuse(*args, **kwargs):
        raise AssertionError("config-check must stay offline")

    monkeypatch.setattr(socket.socket, "connect", refuse)
    monkeypatch.setattr(socket, "getaddrinfo", refuse)
    monkeypatch.setattr(httpx.Client, "__init__", refuse)
    assert build_report()["liveEnvironmentReady"]


def run_cli(tmp_path, env, *args):
    base = {"PATH": "/usr/bin:/bin", **env}
    return subprocess.run([sys.executable, "-m", "zoop_ai.cli", *args], capture_output=True, text=True, env=base,
                          cwd=tmp_path, stdin=subprocess.DEVNULL)


LUNA_ENV = {**{f"ZOOP_AI_{s}_MODEL": "gpt-6-luna" for s in STAGES}, **{f"ZOOP_AI_{s}_REASONING_EFFORT": "low" for s in STAGES},
            "ZOOP_AI_LIVE_ENABLED": "1", "ZOOP_AI_GLOBAL_MAX_CALLS": "4", "ZOOP_AI_API_KEY": SECRET}


def test_cli_config_check_needs_no_state_dir_creates_nothing_and_echoes_no_key(tmp_path):
    done = run_cli(tmp_path, LUNA_ENV, "config-check", "--require-live-prerequisites")
    assert done.returncode == 0 and done.stderr == ""
    body = json.loads(done.stdout)
    assert body["schemaVersion"] == "zoop-ai-config-check-1" and body["liveEnvironmentReady"] and SECRET not in done.stdout
    assert list(tmp_path.iterdir()) == []
    text = run_cli(tmp_path, LUNA_ENV, "config-check", "--format", "text")
    assert text.returncode == 0 and "configValid: true" in text.stdout and SECRET not in text.stdout
    assert "native Jev only when selected" in text.stdout and "not inferred from environment" in text.stdout
    assert list(tmp_path.iterdir()) == []


def test_cli_exit_codes_distinguish_invalid_config_from_missing_live_prerequisites(tmp_path):
    default = run_cli(tmp_path, {}, "config-check")
    assert default.returncode == 0 and json.loads(default.stdout)["liveEnvironmentReady"] is False
    assert run_cli(tmp_path, {}, "config-check", "--require-live-prerequisites").returncode == 2
    invalid = run_cli(tmp_path, {"ZOOP_AI_BASE_URL": "http://api.example.test/v1"}, "config-check")
    assert invalid.returncode == 2 and json.loads(invalid.stdout)["configValid"] is False
    jev = run_cli(tmp_path, LUNA_ENV, "config-check", "--profile", "native-jev")
    assert jev.returncode == 2 and json.loads(jev.stdout)["configValid"] is False
    assert list(tmp_path.iterdir()) == []


def test_cli_config_check_rejects_ledger_arguments_and_other_commands_keep_requiring_state_dir(tmp_path):
    for extra in (["--state-dir", str(tmp_path / "ledger")], ["--grants", "g.json"], ["--replay", "r.json"], ["--initial-only"]):
        assert run_cli(tmp_path, {}, "config-check", *extra).returncode == 2
    assert not (tmp_path / "ledger").exists()
    for command in ("submit", "run", "get", "resume", "cancel"):
        done = run_cli(tmp_path, {}, command)
        assert done.returncode == 2 and "--state-dir" in done.stderr
    done = run_cli(tmp_path, {}, "get", "--state-dir", str(tmp_path / "s"), "--profile", "native-jev")
    assert done.returncode == 2 and "config-check only" in done.stderr


NATIVE_ENV = {**{f"ZOOP_AI_{s}_MODEL": "gpt-6-luna" for s in STAGES if s != "VERIFY"},
              **{f"ZOOP_AI_{s}_REASONING_EFFORT": "low" for s in STAGES if s != "VERIFY"},
              "ZOOP_AI_LIVE_ENABLED": "1", "ZOOP_AI_GLOBAL_MAX_CALLS": "4", "ZOOP_AI_API_KEY": SECRET,
              "ZOOP_AI_VERIFY_PROVIDER": "typesafe-native", "TYPESAFE_VALIDATION_MODEL": "jev-1.14.0", "TYPESAFE_API_KEY": JEV_SECRET}


def test_cli_native_profile_exit_codes_and_masking(tmp_path):
    ready = run_cli(tmp_path, NATIVE_ENV, "config-check", "--profile", "native-jev", "--require-live-prerequisites")
    assert ready.returncode == 0 and json.loads(ready.stdout)["liveEnvironmentReady"] and ready.stderr == ""
    assert JEV_SECRET not in ready.stdout and SECRET not in ready.stdout
    text = run_cli(tmp_path, NATIVE_ENV, "config-check", "--profile", "native-jev", "--format", "text")
    assert text.returncode == 0 and "verification provider: typesafe-native" in text.stdout and JEV_SECRET not in text.stdout
    # The default profile expects the chat verifier and does not silently accept a native selection.
    default = run_cli(tmp_path, NATIVE_ENV, "config-check")
    assert default.returncode == 2 and json.loads(default.stdout)["configValid"] is False
    keyless = run_cli(tmp_path, {k: v for k, v in NATIVE_ENV.items() if k != "TYPESAFE_API_KEY"}, "config-check", "--profile", "native-jev",
                      "--require-live-prerequisites")
    assert keyless.returncode == 2 and json.loads(keyless.stdout)["configValid"] is True
    assert list(tmp_path.iterdir()) == []
