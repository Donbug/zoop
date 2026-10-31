package com.zoop.chat.mcp;

import com.zoop.chat.executor.ChatJobExecutor;
import com.zoop.chat.executor.ChatRun;
import com.zoop.chat.executor.ChatRunControl;
import com.zoop.chat.executor.ChatRunSuperseded;
import com.zoop.chat.orchestrator.ChatAgentPath;
import com.zoop.chat.orchestrator.ChatModels;
import com.zoop.chat.repository.ChatExecutionRepository;
import com.zoop.chat.repository.ChatKeptToolResult;
import com.zoop.chat.tool.ChatCapability;
import com.zoop.chat.tool.ChatToolItem;
import com.zoop.chat.tool.ChatToolPath;
import com.zoop.chat.tool.ChatToolResult;
import com.zoop.chat.tool.ChatToolRunner;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.LinkedHashSet;
import java.util.List;
import java.util.Map;
import java.util.Set;
import tools.jackson.databind.json.JsonMapper;

/**
 * The agent path over the ZOOP MCP endpoint (MCP actions contract 3.4): the server issues the run's grant token, Luna runs in
 * steps, and every tool call Luna proposes is decided here and only here.
 *
 * <ul>
 * <li>A proposed call is approved exactly when it names one of the run's allowed tools and the run's requirements it serves,
 * every target it names is reachable, fewer than {@link #MAX_ROUND_CALLS} calls were approved in its round and
 * {@link ChatMcpTools#approve} reserves it (valid arguments, within the attempt's call limit); otherwise it is denied.
 * Reachable for a requirement are the ids the server resolved for it and, from the next round on, the ids returned by the
 * approved calls that serve it (items, their companies, path endpoints and steps, evidence); a call may use those of the
 * requirements it names. Nothing is approved without being reserved, and a denied call never runs.</li>
 * <li>A read serves at least one requirement that is no general concept: a concept part never rests on internal reads.</li>
 * <li>At most {@link #MAX_ROUNDS} rounds of approvals (the dependency rounds of ZOOP-AIG-001 6.3.3). The step after the last
 * round denies whatever is still asked, so Luna answers from what it has; a run that still asks after that is a failed
 * model step, never an endless loop.</li>
 * <li>A web search (web search design 1 and 2) names a query, not ids, so reachability does not apply. A concept-only run
 * (one or more general requirements, Q02) may make one search from the first round: the web is a concept's first support. Any
 * other search is approved only from a round after an approved internal read came back empty or cut: the web is the last
 * resort of what ZOOP's own data left unmet, never the first look. Its query must pass {@link com.zoop.chat.tool.ChatWebQueryPolicy} and it takes the
 * job's and the day's web budgets when it is reserved; a spent budget denies it and is reported as
 * {@code web_budget_exhausted}.</li>
 * <li>The final answer is returned with the results of the calls that ran, read back from {@code chat_tool_calls.result}:
 * exactly what the model received, whichever instance served the call, with the requirements each one was approved for:
 * a section may cite only the results of its own requirements. Results are never synthesized for a denied
 * call. Beside it go the web faults the answer went on without: an approved search that left no result
 * ({@code web_unavailable}), one that found nothing ({@code web_no_results}), a spent budget.</li>
 * </ul>
 */
public final class ChatMcpAgent implements ChatAgentPath {
    static final int MAX_ROUNDS = 3;
    /** Reads a kept envelope's own fields (what was withheld); never a result passed on. */
    private static final JsonMapper JSON = JsonMapper.builder().build();
    /**
     * Calls approved in one round, so at most this many of the job's calls run at once (MCP actions contract 3.2): the
     * provider makes a round's approved calls before it answers the step, and the next round is decided only then.
     */
    static final int MAX_ROUND_CALLS = 4;

    private final ChatModels.Agent agent;
    private final ChatMcpTools tools;
    private final ChatMcpGrants grants;
    /** The recipient the results' send grants are checked for ({@link ChatSendGrants#recipient}); each step names it. */
    private final String recipient;
    private final ChatExecutionRepository runs;
    private final ChatToolRunner runner;
    /** The MCP preflight and circuit of live runs; null for replay runs, which reach no MCP endpoint. */
    private final ChatMcpCircuitBreaker circuit;

    public ChatMcpAgent(ChatModels.Agent agent, ChatMcpTools tools, ChatMcpGrants grants, String recipient,
            ChatExecutionRepository runs, ChatToolRunner runner, ChatMcpCircuitBreaker circuit) {
        this.agent = agent;
        this.tools = tools;
        this.grants = grants;
        this.recipient = recipient;
        this.runs = runs;
        this.runner = runner;
        this.circuit = circuit;
    }

    @Override
    public boolean available() {
        return circuit == null || circuit.allowAgent();
    }

    @Override
    public Set<ChatCapability> tools() {
        return new LinkedHashSet<>(tools.exposed());
    }

    @Override
    public Outcome run(ChatRun run, ChatRunControl control, List<ChatModels.AgentRequirement> requirements,
            List<ChatCapability> allowed, int maxCitations, Steps steps) {
        String token = grants.issue(run, allowed);
        List<String> names = allowed.stream().map(ChatMcpTools::name).toList();
        var attached = new ChatJobExecutor.Attached(run, control);
        // The ids a call may target, by requirement: what the server resolved for it, then what the calls serving it returned.
        Map<String, Set<String>> reachable = new LinkedHashMap<>();
        requirements.forEach(r -> reachable.put(r.id(), new LinkedHashSet<>(r.targets())));
        Set<String> concepts = new LinkedHashSet<>();
        requirements.stream().filter(ChatModels.AgentRequirement::general).forEach(r -> concepts.add(r.id()));
        // The requirements each approved call serves, by its id on the ledger.
        Map<String, List<String>> served = new LinkedHashMap<>();
        String previous = null;
        List<ChatModels.Decision> decisions = List.of();
        int approved = 0;
        int denied = 0;
        int webApproved = 0;
        long inputTokens = 0;
        Set<String> notices = new LinkedHashSet<>();
        String web = ChatMcpTools.name(ChatCapability.WEB_SEARCH);
        // The web's gate is still decided for the run, not by the requirements a search names, so in a mixed run a first-round
        // query could bypass a fact requirement's internal-first rule: only a concept-only run gets the early search.
        boolean conceptOnly = !requirements.isEmpty()
                && requirements.stream().allMatch(ChatModels.AgentRequirement::general);
        for (int step = 1, rounds = 0; ; step++) {
            var input = new ChatModels.AgentInput(requirements, token, names, recipient, maxCitations, previous,
                    decisions);
            int number = step;
            ChatModels.AgentStep outcome;
            try {
                outcome = steps.run(() -> agent.step(run, number, input));
            } catch (ChatModels.Failure failure) {
                // This run remains failed. The observation affects only the path selected by later jobs.
                if (circuit != null) circuit.agentFailed(failure.code());
                throw failure;
            }
            if (outcome.completed()) {
                List<ChatToolResult> results = kept(run);
                return new Outcome(outcome.answer(), results, served, step, approved, denied,
                        webNotices(results, webApproved, notices, withheldWeb(run)));
            }
            if (rounds > MAX_ROUNDS) {
                throw new ChatModels.Failure(ChatModels.Failure.Fate.NOT_SENT, "the agent kept asking after its last round");
            }
            rounds++;
            // A continuation carries at least what this step took as input. With no room for one more, the run stops unsent;
            // with room for only one, that one writes the answer. A provider that reports nothing counts as nothing.
            long last = outcome.inputTokens() == null ? 0 : outcome.inputTokens();
            inputTokens += last;
            if (inputTokens + last > ChatModels.MAX_INPUT_TOKENS) {
                throw new ChatModels.Failure(ChatModels.Failure.Fate.REFUSED, ChatModels.INPUT_BUDGET_EXCEEDED,
                        "the run has no input tokens left for another step");
            }
            // Past the last round, or with time or tokens for only one more step, nothing more runs: the next step answers.
            boolean closing = rounds > MAX_ROUNDS || steps.closing() || inputTokens + 2 * last > ChatModels.MAX_INPUT_TOKENS;
            if (closing) rounds = MAX_ROUNDS + 1;
            List<ChatToolResult> done = closing ? List.of() : kept(run);
            done.forEach(result -> served.getOrDefault(result.toolCallId(), List.of())
                    .forEach(id -> reachable.get(id).addAll(reached(result))));
            boolean webOpen = unmet(done);
            List<ChatModels.Decision> next = new ArrayList<>();
            int round = 0;
            for (ChatModels.ApprovalRequest request : outcome.approvals()) {
                boolean approve = false;
                boolean search = web.equals(request.toolName());
                // Only the run's own tools, for its requirements, on ids the server resolved for them or a call serving them
                // returned: neither the provider's allowed_tools nor the prompt's "never guess an id" is a server-side
                // check. Past four in a round the rest are denied; Luna may ask for them again in the next round.
                List<String> serves = request.requirementIds();
                if (!closing && round < MAX_ROUND_CALLS && names.contains(request.toolName())
                        && !serves.isEmpty() && reachable.keySet().containsAll(serves)
                        && (search ? webOpen || conceptOnly && webApproved == 0
                                : !concepts.containsAll(serves)
                                        && targetsReachable(request.arguments(), reachableFor(serves, reachable)))) {
                    ChatMcpTools.Approval approval = tools.approve(attached, request.toolName(), request.arguments(), serves);
                    if (ChatMcpTools.RUN_NOT_ACTIVE.equals(approval.refused())) throw new ChatRunSuperseded();
                    if (ChatMcpTools.WEB_BUDGET_EXHAUSTED.equals(approval.refused())) notices.add(WEB_BUDGET_EXHAUSTED);
                    approve = approval.approved();
                    if (approve) served.put(approval.toolCallId(), serves);
                    if (approve && search) webApproved++;
                }
                next.add(new ChatModels.Decision(request.id(), approve));
                if (approve) {
                    approved++;
                    round++;
                } else {
                    denied++;
                }
            }
            previous = outcome.responseId();
            decisions = next;
        }
    }

    static final String WEB_UNAVAILABLE = "web_unavailable";
    static final String WEB_NO_RESULTS = "web_no_results";
    static final String WEB_BUDGET_EXHAUSTED = "web_budget_exhausted";

    /**
     * Whether ZOOP's own reads left something for the web: an approved internal read that found nothing within its scope
     * or was cut by a limit. Decided for the run, whichever requirement the read served.
     */
    static boolean unmet(List<ChatToolResult> done) {
        return done.stream().anyMatch(r -> !ChatCapability.WEB_SEARCH.id().equals(r.capabilityId())
                && (r.items().isEmpty() || Boolean.TRUE.equals(r.truncated())));
    }

    /** The web faults of a finished run, in a fixed order. */
    static List<String> webNotices(List<ChatToolResult> results, int webApproved, Set<String> refused,
            Set<String> withheld) {
        List<ChatToolResult> searches = results.stream()
                .filter(r -> ChatCapability.WEB_SEARCH.id().equals(r.capabilityId())).toList();
        Set<String> notices = new LinkedHashSet<>();
        // An approved search with no kept result failed, timed out or never came back. A successful provider response whose
        // hits were all withheld by the send grant is unavailable to the answer too, never "no results".
        if (searches.size() < webApproved || !withheld.isEmpty()) notices.add(WEB_UNAVAILABLE);
        if (searches.stream().anyMatch(r -> r.webResults().isEmpty() && !Boolean.TRUE.equals(r.truncated())
                && !withheld.contains(r.toolCallId()))) {
            notices.add(WEB_NO_RESULTS);
        }
        notices.addAll(refused);
        return List.copyOf(notices);
    }

    /** Web calls whose provider returned hits but the model-send grant withheld them all. */
    private Set<String> withheldWeb(ChatRun run) {
        Set<String> withheld = new LinkedHashSet<>();
        for (ChatKeptToolResult kept : runs.keptToolResults(run.jobId(), run.attemptNo())) {
            if (!ChatCapability.WEB_SEARCH.id().equals(kept.capabilityId())) continue;
            if (JSON.readTree(kept.result()).path("withheld").path("webResults").asInt(0) > 0) {
                withheld.add(kept.toolCallId());
            }
        }
        return withheld;
    }

    /**
     * Whether every target of a proposed call is reachable. A call without {@code targets} reads what the server fixes for
     * it (the fixed ZOOP documents, or the whole public graph of a version diff) and is left to the argument check; any other
     * shape is refused there too.
     */
    static boolean targetsReachable(Map<String, Object> arguments, Set<String> reachable) {
        if (!arguments.containsKey("targets")) return true;
        if (!(arguments.get("targets") instanceof List<?> targets)) return false;
        return targets.stream().allMatch(target -> target instanceof String id && reachable.contains(id));
    }

    private static Set<String> reachableFor(List<String> requirementIds, Map<String, Set<String>> reachable) {
        Set<String> ids = new LinkedHashSet<>();
        requirementIds.forEach(id -> ids.addAll(reachable.get(id)));
        return ids;
    }

    /** The ids a result made known: its items and their companies, path endpoints and steps, and its evidence. */
    static Set<String> reached(ChatToolResult result) {
        Set<String> ids = new LinkedHashSet<>(result.evidenceIds());
        for (ChatToolItem item : result.items()) {
            ids.add(item.id());
            ids.addAll(item.companyIds());
            ids.addAll(item.evidenceIds());
        }
        for (ChatToolPath path : result.paths()) {
            ids.add(path.fromId());
            ids.add(path.toId());
            for (ChatToolPath.Step step : path.steps()) {
                ids.add(step.sourceId());
                ids.add(step.targetId());
                ids.addAll(step.evidenceIds());
            }
        }
        return ids;
    }

    /**
     * The results the attempt's MCP calls returned to the model, as kept on the ledger and rebound to this run: a kept
     * result that does not belong to it is refused, never passed on.
     */
    private List<ChatToolResult> kept(ChatRun run) {
        return runner.restore(run, runs.keptToolResults(run.jobId(), run.attemptNo()));
    }
}
