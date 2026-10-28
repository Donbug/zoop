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
import java.util.ArrayList;
import java.util.LinkedHashSet;
import java.util.List;
import java.util.Set;
import tools.jackson.core.type.TypeReference;
import tools.jackson.databind.JsonNode;
import tools.jackson.databind.ObjectMapper;

/**
 * The agent path over the ZOOP MCP endpoint (MCP actions contract 3.4): the server issues the run's grant token, Luna runs in
 * steps, and every tool call Luna proposes is decided here and only here.
 *
 * <ul>
 * <li>A proposed call is approved exactly when it names one of the run's allowed tools and {@link ChatMcpTools#approve}
 * reserves it (valid arguments, within the attempt's call limit); otherwise it is denied. Nothing is approved without being reserved, and a denied call
 * never runs.</li>
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
    private static final TypeReference<List<ChatToolItem>> ITEMS = new TypeReference<>() { };
    private static final TypeReference<List<ChatToolPath>> PATHS = new TypeReference<>() { };
    private static final TypeReference<List<String>> STRINGS = new TypeReference<>() { };

    private final ChatModels.Agent agent;
    private final ChatMcpTools tools;
    private final ChatMcpGrants grants;
    private final ChatExecutionRepository runs;
    private final ObjectMapper mapper;

    public ChatMcpAgent(ChatModels.Agent agent, ChatMcpTools tools, ChatMcpGrants grants, ChatExecutionRepository runs,
            ObjectMapper mapper) {
        this.agent = agent;
        this.tools = tools;
        this.grants = grants;
        this.runs = runs;
        this.mapper = mapper;
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
        String previous = null;
        List<ChatModels.Decision> decisions = List.of();
        int approved = 0;
        int denied = 0;
        for (int step = 1, rounds = 0; ; step++) {
            var input = new ChatModels.AgentInput(requirements, token, names, maxCitations, previous, decisions);
            int number = step;
            ChatModels.AgentStep outcome = steps.run(() -> agent.step(run, number, input));
            if (outcome.completed()) return new Outcome(outcome.answer(), kept(run), step, approved, denied);
            if (rounds > MAX_ROUNDS) {
                throw new ChatModels.Failure(ChatModels.Failure.Fate.NOT_SENT, "the agent kept asking after its last round");
            }
            rounds++;
            // Past the last round, or with time for only one more step, nothing more runs: the next step writes the answer.
            boolean closing = rounds > MAX_ROUNDS || steps.closing();
            if (closing) rounds = MAX_ROUNDS + 1;
            List<ChatModels.Decision> next = new ArrayList<>();
            for (ChatModels.ApprovalRequest request : outcome.approvals()) {
                boolean approve = false;
                // Only the run's own tools: the provider's allowed_tools is no server-side check.
                if (!closing && names.contains(request.toolName())) {
                    ChatMcpTools.Approval approval = tools.approve(attached, request.toolName(), request.arguments());
                    if (ChatMcpTools.RUN_NOT_ACTIVE.equals(approval.refused())) throw new ChatRunSuperseded();
                    approve = approval.approved();
                }
                next.add(new ChatModels.Decision(request.id(), approve));
                if (approve) approved++;
                else denied++;
            }
            previous = outcome.responseId();
            decisions = next;
        }
    }

    /** The results the attempt's MCP calls returned to the model, as kept on the ledger. */
    private List<ChatToolResult> kept(ChatRun run) {
        List<ChatToolResult> results = new ArrayList<>();
        for (ChatKeptToolResult kept : runs.keptToolResults(run.jobId(), run.attemptNo())) {
            JsonNode node = mapper.readTree(kept.result());
            results.add(new ChatToolResult(node.path("schemaVersion").asString(), kept.toolCallId(), kept.capabilityId(),
                    node.path("dataVersion").asString(null), mapper.convertValue(node.path("items"), ITEMS),
                    mapper.convertValue(node.path("evidenceIds"), STRINGS),
                    node.path("truncated").isBoolean() ? node.path("truncated").asBoolean() : null,
                    node.path("nextAllowed").isBoolean() ? node.path("nextAllowed").asBoolean() : null, null,
                    node.has("paths") ? mapper.convertValue(node.path("paths"), PATHS) : List.of()));
        }
        return results;
    }
}
