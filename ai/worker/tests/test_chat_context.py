"""Agent continuation admission uses its latest held context and bounded newly approved callbacks."""
from chat_resource_support import configured_chat
from test_chat_agent import Endpoint, agent_input, approval_response, continuation, final_response, answer, request, run


def held(response_id, approval_id):
    raw = approval_response((approval_id, "company_read", {}))
    raw["id"] = response_id
    raw["usage"]["input_tokens"] = 130000
    return raw


def test_current_context_continues_beyond_cumulative_billing_but_reserves_each_unknown_result(tmp_path):
    outcomes = []
    payload = agent_input()
    for step in range(1, 5):
        result = run(request(payload, invocation=f"app:job:agent-{step}"), tmp_path,
                     Endpoint(held(f"resp_held_{step}", f"mcpr_{step}")))
        assert result.status == "succeeded", result
        outcomes.append(result)
        payload = agent_input(continuation=continuation((f"mcpr_{step}", True), previous=f"resp_held_{step}"))
    final_payload = payload
    final = run(request(final_payload, invocation="app:job:agent-5"), tmp_path, Endpoint(final_response(answer())))
    assert final.status == "succeeded", final
    assert sum(item.receipt.usage.input_tokens for item in outcomes) > 512000

    wrong_principal = run(request(final_payload, invocation="other:job:agent-4"), tmp_path, Endpoint())
    assert wrong_principal.failure.code == "agent_context_unavailable" and not wrong_principal.failure.sent

    state = tmp_path / "two-results"
    state.mkdir()
    two = approval_response(("mcpr_a", "company_read", {}), ("mcpr_b", "company_read", {}))
    two["id"] = "resp_two"
    seeded = run(request(agent_input(), invocation="app:job:two"), state, Endpoint(two))
    assert seeded.status == "succeeded"
    endpoint = Endpoint()
    unsafe = run(request(agent_input(continuation=continuation(("mcpr_a", True), ("mcpr_b", True), previous="resp_two")),
                         invocation="app:job:too-large"), state, endpoint)
    assert unsafe.failure.code == "input_budget_exceeded" and not unsafe.failure.sent and endpoint.calls == []


def test_unknown_continuations_are_unsent(tmp_path):
    endpoint = Endpoint()
    unknown = run(request(agent_input(continuation=continuation(("unknown", True)))), tmp_path, endpoint)
    assert unknown.failure.code == "agent_context_unavailable" and not unknown.failure.sent and endpoint.calls == []
