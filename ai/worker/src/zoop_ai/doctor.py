"""Offline S1 configuration doctor behind `zoop-ai config-check`.

It only reads this process's environment. It opens no socket, creates no state directory or file, reads no grant
registry, constructs no provider and sends no request. Secret values (API keys, proxy URLs, URL userinfo) and raw
invalid values are never copied into the report: problems are reported as `{severity, field, code}` where `field` is
a fixed environment variable name. Stage validation is the worker's own `stage_config`; the endpoint rule is the
provider's own `validate_base_url`. The report distinguishes three things that must never be inferred from one
another: the configuration parses (`configValid`), the live prerequisites are present (`liveEnvironmentReady`), and
spending is authorized (never decided here). Account and model availability is never checked.

The profile states which verification route the operator expects. `s1-openai-compatible` expects every stage on the
OpenAI-compatible adapter; `native-jev` expects semantic-verification on the native Jev adapter. The environment decides
what actually runs (`ZOOP_AI_VERIFY_PROVIDER`), and a mismatch is an error rather than a silent switch.
"""
from __future__ import annotations

import os
import re
import urllib.request
from typing import Any

import httpx

from . import native_jev
from .contracts import digest
from .provider import (DEFAULT_BASE_URL, EFFORTS, NATIVE_DEFAULT_BASE_URL, NATIVE_PROVIDER, STAGE_ENV, VERIFY_PROVIDERS,
                       ProviderError, native_revision, stage_config, validate_base_url)

REPORT_VERSION = "zoop-ai-config-check-1"
PROFILES = ("s1-openai-compatible", "native-jev")
MODEL_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/+-]{0,95}$")
SECRET_LIKE = re.compile(r"^(sk|sess|bearer)[-_]", re.IGNORECASE)
NATIVE_JEV_MODEL = re.compile(r"^jev[-.]", re.IGNORECASE)
NATIVE_JEV_HOST_SUFFIX = "typesafe.ai"
# Reviewed against first-party documentation on 2026-10-15; never verified against an account.
KNOWN_MODELS: dict[str, dict[str, Any]] = {
    "gpt-6-luna": {"efforts": frozenset({"none", "low", "medium", "high", "xhigh", "max"}),
                   "source": "https://developers.openai.com/api/docs/models/gpt-6-luna"},
}
STAGE_ORDER = ("document-summary", "document-sentiment", "semantic-verification", "briefing-outlook")
DOCUMENT_STAGES = {"document-summary", "document-sentiment", "semantic-verification"}
CAPABILITIES = {
    "s1": {"liveTransport": "openai-compatible-chat-completions", "structuredOutput": "json_schema-strict",
           "toolCalling": False, "responsesApi": False},
    "s2": {"live": False, "mode": "replay_only"},
    "s3": {"live": False, "mode": "replay_only"},
}
CAPABILITY_GAPS = [
    {"code": "responses_api_not_implemented",
     "note": "Reasoning effort above none together with tools needs the Responses API for gpt-6-luna. S1 sends no tools, so its chat call is valid."},
    {"code": "native_jev_thresholds_uncalibrated",
     "note": "Native Jev serves semantic-verification only. Its Choice (p>=0.90 and confidence>=0.80) and Noul (>=0.90 / <=0.10) thresholds are "
             "provisional engineering values, not calibrated against Zoop-labelled data and not an acceptance criterion."},
    {"code": "s2_s3_live_not_implemented", "note": "S2 extraction and S3 relation are replay-only."},
]


def _env(name: str) -> str | None:
    return os.environ.get(name)


def _issue(issues: list[dict[str, str]], severity: str, field: str, code: str) -> None:
    item = {"severity": severity, "field": field, "code": code}
    if item not in issues:
        issues.append(item)


def _ascii_token(value: str) -> bool:
    return all(33 <= ord(c) <= 126 for c in value)


def _endpoint(issues: list[dict[str, str]], *, field: str = "ZOOP_AI_BASE_URL", default: str = DEFAULT_BASE_URL,
              native: bool = False) -> dict[str, Any]:
    raw = _env(field)
    raw = default if raw is None else raw
    report: dict[str, Any] = {"valid": False}
    try:
        url = httpx.URL(raw)
    except httpx.InvalidURL:
        _issue(issues, "error", field, "base_url_malformed")
        return report
    try:
        validate_base_url(raw)
    except ProviderError as exc:
        _issue(issues, "error", field, exc.code)
        return report
    problems = False
    if url.userinfo:
        _issue(issues, "error", field, "base_url_userinfo_forbidden")
        problems = True
    if url.query or url.fragment:
        _issue(issues, "error", field, "base_url_query_or_fragment_forbidden")
        problems = True
    host = url.host.lower()
    default_host = httpx.URL(default).host
    if native:
        # The adapter appends `systemone` itself; a base URL that already ends in it would post to `.../systemone/systemone`.
        if url.path.rstrip("/").lower().endswith("/" + native_jev.API):
            _issue(issues, "error", field, "native_base_url_includes_endpoint_path")
            problems = True
        if host != default_host:
            _issue(issues, "warning", field, "endpoint_not_default_typesafe_host")
    else:
        if host == NATIVE_JEV_HOST_SUFFIX or host.endswith("." + NATIVE_JEV_HOST_SUFFIX) or "systemone" in url.path.lower():
            _issue(issues, "error", field, "native_jev_endpoint_not_openai_compatible")
            problems = True
        if host != default_host:
            _issue(issues, "warning", field, "endpoint_not_default_openai_host")
    if url.scheme == "http":
        _issue(issues, "warning", field, "endpoint_loopback_plain_http")
    proxies = urllib.request.getproxies_environment()
    configured = sorted(proxies)
    routed = bool((proxies.get(url.scheme) or proxies.get("all")) and not urllib.request.proxy_bypass_environment(host, proxies))
    if routed:
        _issue(issues, "warning", f"{url.scheme.upper()}_PROXY", "proxy_env_routes_endpoint")
    if any(_env(name) for name in ("SSL_CERT_FILE", "SSL_CERT_DIR")):
        _issue(issues, "warning", "SSL_CERT_FILE", "custom_ca_env_present")
    report.update({"valid": not problems, "scheme": url.scheme, "host": host, "port": url.port,
                   "defaultTypesafeHost" if native else "defaultOpenAiHost": host == default_host,
                   "proxy": {"configuredSchemes": configured, "routesEndpoint": routed},
                   "httpxTrustsEnvironment": True})
    if not problems:
        report["providerRevision"] = native_revision(raw) if native else digest({"endpoint": raw})
    return report


def _stage(kind: str, issues: list[dict[str, str]]) -> dict[str, Any]:
    prefix = f"ZOOP_AI_{STAGE_ENV[kind]}"
    model_field, effort_field = prefix + "_MODEL", prefix + "_REASONING_EFFORT"
    model_raw = (_env(model_field) or "").strip()
    effort_raw = (_env(effort_field) or "").strip()
    local: list[dict[str, str]] = []
    try:
        stage_config(kind, "live")
    except ProviderError as exc:
        provider_field = ("ZOOP_AI_VERIFY_PROVIDER" if kind == "semantic-verification"
                          and (_env("ZOOP_AI_VERIFY_PROVIDER") or "").strip() not in {"", *VERIFY_PROVIDERS} else "ZOOP_AI_PROVIDER")
        field = {"stage_model_required": model_field, "reasoning_effort_invalid": effort_field}.get(exc.code, provider_field)
        _issue(local, "blocker" if exc.code == "stage_model_required" else "error", field, exc.code)
    model: str | None = None
    state = "missing"
    known = False
    if model_raw:
        if not MODEL_PATTERN.fullmatch(model_raw) or SECRET_LIKE.match(model_raw):
            state = "malformed"
            _issue(local, "error", model_field, "stage_model_malformed")
        else:
            state, model = "set", model_raw
            if NATIVE_JEV_MODEL.match(model_raw):
                _issue(local, "error", model_field, "native_jev_model_on_openai_compatible_chat")
            else:
                info = KNOWN_MODELS.get(model_raw)
                known = info is not None
                if info is None:
                    _issue(local, "warning", model_field, "stage_model_not_in_reviewed_list")
                elif effort_raw in EFFORTS and effort_raw not in info["efforts"]:
                    _issue(local, "error", effort_field, "reasoning_effort_unsupported_for_model")
                if not effort_raw:
                    _issue(local, "warning", effort_field, "reasoning_effort_unset_provider_default_applies")
    for item in local:
        _issue(issues, item["severity"], item["field"], item["code"])
    severities = {i["severity"] for i in local}
    return {"kind": kind, "provider": "openai-compatible", "env": {"model": model_field, "reasoningEffort": effort_field},
            "model": model, "modelState": state, "reviewedModel": known,
            "reasoningEffort": effort_raw if effort_raw in EFFORTS else None,
            "reasoningEffortState": "unset" if not effort_raw else ("set" if effort_raw in EFFORTS else "invalid"),
            "requiredFor": "document-jobs" if kind in DOCUMENT_STAGES else "briefing-outlook-jobs",
            "status": "invalid" if "error" in severities else ("blocked" if "blocker" in severities else "ready"),
            "issueCodes": [i["code"] for i in local]}


def _native_stage(issues: list[dict[str, str]]) -> dict[str, Any]:
    """semantic-verification on native Jev: the model comes from TYPESAFE_VALIDATION_MODEL and must be the pinned one; effort does
    not apply, and the OpenAI-compatible verify settings must be gone rather than silently ignored."""
    kind, model_field = "semantic-verification", "TYPESAFE_VALIDATION_MODEL"
    model_raw = (_env(model_field) or "").strip()
    local: list[dict[str, str]] = []
    if (_env("ZOOP_AI_VERIFY_MODEL") or "").strip():
        _issue(local, "error", "ZOOP_AI_VERIFY_MODEL", "native_verify_stale_model_setting")
    if (_env("ZOOP_AI_VERIFY_REASONING_EFFORT") or "").strip():
        _issue(local, "error", "ZOOP_AI_VERIFY_REASONING_EFFORT", "native_verify_stale_effort_setting")
    model: str | None = None
    state = "missing"
    if not model_raw:
        _issue(local, "blocker", model_field, "stage_model_required")
    elif not MODEL_PATTERN.fullmatch(model_raw) or SECRET_LIKE.match(model_raw):
        state = "malformed"
        _issue(local, "error", model_field, "stage_model_malformed")
    else:
        state, model = "set", model_raw
        if model_raw != native_jev.MODEL:
            _issue(local, "error", model_field, "native_model_unsupported")
    if not local:
        try:
            stage_config(kind, "live")
        except ProviderError as exc:
            _issue(local, "error", "ZOOP_AI_VERIFY_PROVIDER", exc.code)
    for item in local:
        _issue(issues, item["severity"], item["field"], item["code"])
    severities = {i["severity"] for i in local}
    return {"kind": kind, "provider": NATIVE_PROVIDER, "env": {"model": model_field, "reasoningEffort": None},
            "model": model, "modelState": state, "reviewedModel": model == native_jev.MODEL,
            "reasoningEffort": None, "reasoningEffortState": "not_applicable",
            "requiredFor": "document-jobs",
            "status": "invalid" if "error" in severities else ("blocked" if "blocker" in severities else "ready"),
            "issueCodes": [i["code"] for i in local]}


def build_report(profile: str = "s1-openai-compatible") -> dict[str, Any]:
    issues: list[dict[str, str]] = []
    if profile not in PROFILES:
        raise ValueError(profile)
    verify_raw = (_env("ZOOP_AI_VERIFY_PROVIDER") or "").strip()
    verify = verify_raw or "openai-compatible"
    native = verify == NATIVE_PROVIDER
    if verify not in VERIFY_PROVIDERS:
        _issue(issues, "error", "ZOOP_AI_VERIFY_PROVIDER", "provider_unsupported")
    elif profile == "native-jev" and not native:
        _issue(issues, "error", "ZOOP_AI_VERIFY_PROVIDER", "native_verify_not_selected")
    elif profile != "native-jev" and native:
        _issue(issues, "error", "ZOOP_AI_VERIFY_PROVIDER", "native_verify_selected_use_native_jev_profile")
    flag = _env("ZOOP_AI_LIVE_ENABLED")
    enabled = flag == "1"
    if flag is not None and flag not in {"", "0", "1"}:
        _issue(issues, "warning", "ZOOP_AI_LIVE_ENABLED", "live_enabled_value_ignored_only_1_enables")
    ceiling: int | None
    try:
        ceiling = int(os.environ.get("ZOOP_AI_GLOBAL_MAX_CALLS", "0"))
    except ValueError:
        ceiling = None
        _issue(issues, "error", "ZOOP_AI_GLOBAL_MAX_CALLS", "global_max_calls_invalid")
    if not enabled:
        _issue(issues, "blocker", "ZOOP_AI_LIVE_ENABLED", "live_not_enabled")
    if ceiling is not None and ceiling <= 0:
        _issue(issues, "blocker", "ZOOP_AI_GLOBAL_MAX_CALLS", "global_max_calls_not_positive")
    key = _env("ZOOP_AI_API_KEY") or ""
    if not key:
        _issue(issues, "blocker", "ZOOP_AI_API_KEY", "api_key_required")
        if _env("OPENAI_API_KEY"):
            _issue(issues, "warning", "OPENAI_API_KEY", "openai_api_key_env_not_read_use_zoop_ai_api_key")
    elif not _ascii_token(key):
        _issue(issues, "error", "ZOOP_AI_API_KEY", "api_key_malformed")
    typesafe_key = _env("TYPESAFE_API_KEY") or ""
    if native:
        if not typesafe_key:
            _issue(issues, "blocker", "TYPESAFE_API_KEY", "typesafe_api_key_required")
        elif not _ascii_token(typesafe_key):
            _issue(issues, "error", "TYPESAFE_API_KEY", "typesafe_api_key_malformed")
    elif any(_env(n) for n in ("TYPESAFE_API_KEY", "TYPESAFE_BASE_URL", "TYPESAFE_VALIDATION_MODEL")):
        _issue(issues, "warning", "TYPESAFE_API_KEY", "typesafe_env_present_native_verify_not_selected")
    provider = _env("ZOOP_AI_PROVIDER")
    provider = "openai-compatible" if provider is None else provider
    if provider != "openai-compatible":
        _issue(issues, "error", "ZOOP_AI_PROVIDER", "provider_unsupported")
    endpoint = _endpoint(issues)
    native_endpoint = _endpoint(issues, field="TYPESAFE_BASE_URL", default=NATIVE_DEFAULT_BASE_URL, native=True) if native else None
    stages = [_native_stage(issues) if native and kind == "semantic-verification" else _stage(kind, issues) for kind in STAGE_ORDER]
    errors = [i for i in issues if i["severity"] == "error"]
    blockers = [i for i in issues if i["severity"] == "blocker"]
    return {
        "schemaVersion": REPORT_VERSION,
        "profile": profile,
        "offline": {"networkRequests": 0, "stateAccess": "none", "grantsRead": False, "providerConstructed": False},
        "configValid": not errors,
        "liveEnvironmentReady": not errors and not blockers,
        "authorization": {"liveSpend": "not_inferred_from_environment",
                          "accountAndModelAvailability": "unverified_no_request_sent"},
        "liveGate": {"enabledFlag": enabled, "globalMaxCalls": ceiling,
                     "ceilingPositive": ceiling is not None and ceiling > 0, "apiKeyPresent": bool(key),
                     "typesafeApiKeyPresent": bool(typesafe_key)},
        "budget": {"unit": "calls", "enforcedBy": "durable per-ledger call-count reservation",
                   "costCap": None, "tokenCap": None},
        "provider": {"name": provider if provider == "openai-compatible" else None, "supported": provider == "openai-compatible"},
        "verifyProvider": {"name": verify if verify in VERIFY_PROVIDERS else None, "supported": verify in VERIFY_PROVIDERS,
                           "selectedBy": "ZOOP_AI_VERIFY_PROVIDER" if verify_raw else "default"},
        "endpoint": endpoint,
        "nativeEndpoint": native_endpoint,
        "stages": stages,
        "capabilities": {**CAPABILITIES,
                         "nativeJev": {"adapter": True, "scope": "semantic-verification", "api": "POST /v1/systemone",
                                       "model": native_jev.MODEL, "selected": native, "thresholds": "provisional_uncalibrated"}},
        "capabilityGaps": CAPABILITY_GAPS,
        "productionProfile": {"status": "not_available",
                              "reasons": ["s2_s3_live_not_implemented", "native_jev_thresholds_uncalibrated"]},
        "issues": issues,
    }


def render_text(report: dict[str, Any]) -> str:
    lines = [f"zoop-ai config-check ({report['profile']}) — offline: no request, no state, no grant read",
             f"configValid: {str(report['configValid']).lower()}   liveEnvironmentReady: {str(report['liveEnvironmentReady']).lower()}",
             "live spend authorization: not inferred from environment; account/model availability: unverified (no request sent)"]
    gate = report["liveGate"]
    lines.append(f"live gate: enabled={gate['enabledFlag']} globalMaxCalls={gate['globalMaxCalls']} apiKeyPresent={gate['apiKeyPresent']} "
                 f"typesafeApiKeyPresent={gate['typesafeApiKeyPresent']} (budget unit: calls only)")
    endpoint = report["endpoint"]
    if endpoint.get("valid"):
        lines.append(f"endpoint: {endpoint['scheme']}://{endpoint['host']} defaultOpenAiHost={endpoint['defaultOpenAiHost']} proxyRoutes={endpoint['proxy']['routesEndpoint']}")
    else:
        lines.append("endpoint: invalid or unsafe (see issues)")
    lines.append(f"verification provider: {report['verifyProvider']['name'] or 'unsupported'}")
    native = report["nativeEndpoint"]
    if native is not None:
        if native.get("valid"):
            lines.append(f"native endpoint: {native['scheme']}://{native['host']} defaultTypesafeHost={native['defaultTypesafeHost']} proxyRoutes={native['proxy']['routesEndpoint']}")
        else:
            lines.append("native endpoint: invalid or unsafe (see issues)")
    for stage in report["stages"]:
        lines.append(f"stage {stage['kind']}: {stage['status']} provider={stage['provider']} model={stage['model'] or '-'} effort={stage['reasoningEffort'] or '-'}")
    lines.append("runtime: S1 live = OpenAI-compatible chat; semantic-verification is native Jev only when selected (provisional thresholds); "
                 "S2/S3 replay-only; production profile not available")
    for item in report["issues"]:
        lines.append(f"{item['severity']}: {item['field']} {item['code']}")
    return "\n".join(lines)
