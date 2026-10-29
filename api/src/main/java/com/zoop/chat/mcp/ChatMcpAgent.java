package com.zoop.chat.mcp;

import com.zoop.chat.executor.ChatJobExecutor;
import com.zoop.chat.executor.ChatRun;
import com.zoop.chat.executor.ChatRunControl;
import com.zoop.chat.executor.ChatRunSuperseded;
import com.zoop.chat.orchestrator.ChatAgentPath;
import com.zoop.chat.orchestrator.ChatModels;
import com.zoop.chat.repository.ChatExecutionRepository;
import com.zoop.chat.tool.ChatCapability;
import com.zoop.chat.tool.ChatToolItem;
import com.zoop.chat.tool.ChatToolPath;
import com.zoop.chat.tool.ChatToolResult;
import com.zoop.chat.tool.ChatToolRunner;
import java.util.ArrayList;
import java.util.LinkedHashSet;
import java.util.List;
import java.util.Map;
import java.util.Set;

/**
 * The agent path over the ZOOP MCP endpoint (MCP actions contract 3.4): the server issues the run's grant token, Luna runs in
 * steps, and every tool call Luna proposes is decided here and only here.
 *
 * <ul>
 * <li>A proposed call is approved exactly when it names one of the run's allowed tools, every target it names is reachable,
 * fewer than {@link #MAX_ROUND_CALLS} calls were approved in its round and {@link ChatMcpTools#approve} reserves it (valid
 * arguments, within the attempt's call limit); otherwise it is denied.
 * Reachable are the ids the server resolved for the requirements and, from the next round on, the ids the calls it
 * approved returned (items, their companies, path endpoints and steps, evidence). Nothing is approved without being
 * reserved, and a denied call never runs.</li>
 * <li>At most {@link #MAX_ROUNDS} rounds of approvals (the dependency rounds of ZOOP-AIG-001 6.3.3). The step after the last
 * round denies whatever is still asked, so Luna answers from what it has; a run that still asks after that is a failed
 * model step, never an endless loop.</li>
 * <li>The final answer is returned with the results of the calls that ran, read back from {@code chat_tool_calls.result}:
 * exactly what the model received, whichever instance served the call. Results are never synthesized for a denied
 * call.</li>
 * </ul>
 */
public final class ChatMcpAgent implements ChatAgentPath {
    static final int MAX_ROUNDS = 3;
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
        return circuit.allowAgent();
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
        // The ids a call may target: what the server resolved for the requirements, then what approved calls returned.
        Set<String> reachable = new LinkedHashSet<>();
        requirements.forEach(r -> reachable.addAll(r.targets()));
        String previous = null;
        List<ChatModels.Decision> decisions = List.of();
        int approved = 0;
        int denied = 0;
        for (int step = 1, rounds = 0; ; step++) {
            var input = new ChatModels.AgentInput(requirements, token, names, recipient, maxCitations, previous,
                    decisions);
            int number = step;
            ChatModels.AgentStep outcome;
            try {
                outcome = steps.run(() -> agent.step(run, number, input));
            } catch (ChatModels.Failure failure) {
                // This run remains failed. The observation affects only the path selected by later jobs.
                circuit.agentFailed(failure.code());
                throw failure;
            }
            if (outcome.completed()) return new Outcome(outcome.answer(), kept(run), step, approved, denied);
            if (rounds > MAX_ROUNDS) {
                throw new ChatModels.Failure(ChatModels.Failure.Fate.NOT_SENT, "the agent kept asking after its last round");
            }
            rounds++;
            // Past the last round, or with time for only one more step, nothing more runs: the next step writes the answer.
            boolean closing = rounds > MAX_ROUNDS || steps.closing();
            if (closing) rounds = MAX_ROUNDS + 1;
            if (!closing) kept(run).forEach(result -> reachable.addAll(reached(result)));
            List<ChatModels.Decision> next = new ArrayList<>();
            int round = 0;
            for (ChatModels.ApprovalRequest request : outcome.approvals()) {
                boolean approve = false;
                // Only the run's own tools on ids the server resolved or a call it approved returned: neither the
                // provider's allowed_tools nor the prompt's "never guess an id" is a server-side check. Past four in a
                // round the rest are denied; Luna may ask for them again in the next round.
                if (!closing && round < MAX_ROUND_CALLS && names.contains(request.toolName())
                        && targetsReachable(request.arguments(), reachable)) {
                    ChatMcpTools.Approval approval = tools.approve(attached, request.toolName(), request.arguments());
                    if (ChatMcpTools.RUN_NOT_ACTIVE.equals(approval.refused())) throw new ChatRunSuperseded();
                    approve = approval.approved();
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
        return runs.keptToolResults(run.jobId(), run.attemptNo()).stream().map(kept -> runner.restore(run, kept)).toList();
    }
}
