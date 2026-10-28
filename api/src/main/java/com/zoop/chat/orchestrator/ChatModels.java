package com.zoop.chat.orchestrator;

import com.zoop.chat.dto.Citation;
import com.zoop.chat.executor.ChatRun;
import java.util.List;
import java.util.Map;
import java.util.Set;

/**
 * The model stages the orchestrator calls, as typed ports (design summary 3): the router (Jev), the answer generator (Luna
 * {@code answer-generator}) and the semantic verifier (Jev {@code semantic-verification}). Each is called at most once per
 * run, only after {@code ChatRunControl.beforeModelCall()}. None of them sees a tool, a member id or a database: they get
 * structured input and return typed output the server checks.
 *
 * <p>The production adapter is {@code com.zoop.chat.model.ChatModelStages}; the engine is registered only with
 * {@code zoop.ai.chat-client.enabled=true}, and question intake stays off without it.
 */
public final class ChatModels {
    private ChatModels() {
    }

    /** Jev router: the question chain and its frozen selection → requirements with typed probabilities. */
    public interface Router {
        ChatRouteDecision route(ChatRun run, Set<String> boundCapabilities);
    }

    /** Luna answer generator: answers the answerable requirements of the run from their branch context. */
    public interface Generator {
        ChatGeneratedAnswer generate(ChatRun run, ChatBranchContext context);
    }

    /** Jev semantic verification of the sections that passed the deterministic checks. */
    public interface Verifier {
        ChatSemanticVerdicts verify(ChatRun run, List<ChatGeneratedAnswer.Section> sections, List<Citation> citations);
    }

    /**
     * One step of the Luna agent run with the ZOOP MCP tools ({@code chat-agent}, MCP actions contract 3.4): the first step
     * (no {@code previousResponseId}) or a continuation with the server's decisions. {@code step} numbers the steps of the
     * run from 1; each step is its own model call. Luna proposes tool calls; only the server decides them.
     */
    public interface Agent {
        AgentStep step(ChatRun run, int step, AgentInput input);
    }

    /** A requirement the agent answers, with the ids the server already resolved for it. */
    public record AgentRequirement(String id, String label, boolean general, List<String> targets) {
        public AgentRequirement {
            targets = List.copyOf(targets);
        }
    }

    /** The server's decision on one approval request. */
    public record Decision(String approvalRequestId, boolean approve) { }

    /**
     * What one agent step sends: the requirements, the run's grant token, the tools the run may use and, for a continuation,
     * the stored response and the server's decisions on it. The MCP server's URL is no part of it: the AI runtime sends grants
     * only to its operator's configured server ({@code ZOOP_AI_CHAT_MCP_SERVER_URL}).
     */
    public record AgentInput(List<AgentRequirement> requirements, String grantToken, List<String> allowedTools,
            int maxCitations, String previousResponseId, List<Decision> decisions) {
        public AgentInput {
            requirements = List.copyOf(requirements);
            allowedTools = List.copyOf(allowedTools);
            decisions = List.copyOf(decisions);
            if ((previousResponseId == null) != decisions.isEmpty()) {
                throw new IllegalArgumentException("a continuation, and only a continuation, carries decisions");
            }
        }
    }

    /** A tool call Luna proposed, held by the provider until the server decides. */
    public record ApprovalRequest(String id, String toolName, Map<String, Object> arguments) {
        public ApprovalRequest {
            // A model may write an explicit null; the server's argument check refuses it, so it is kept as written.
            arguments = java.util.Collections.unmodifiableMap(new java.util.LinkedHashMap<>(arguments));
        }
    }

    /** One step's outcome: held at {@code approvals} (no answer), or the final {@code answer} (no approvals). */
    public record AgentStep(String responseId, List<ApprovalRequest> approvals, ChatGeneratedAnswer answer) {
        public AgentStep {
            approvals = List.copyOf(approvals);
            if (approvals.isEmpty() == (answer == null)) {
                throw new IllegalArgumentException("an agent step is held at approvals or completed with an answer");
            }
        }

        public boolean completed() {
            return answer != null;
        }
    }

    /**
     * A model stage failed. {@code fate} says whether the provider may have processed the request: {@link Fate#NOT_SENT}
     * (nothing sent, or a confirmed refusal or malformed answer) may be rerun; {@link Fate#UNKNOWN} (sent, then timed out or
     * disconnected) never is, because the provider may have processed and charged it; {@link Fate#REFUSED} (a policy or
     * configuration refusal: no source grant, the live gate closed, the call budget spent) is not rerun because the same run
     * would be refused again.
     */
    public static final class Failure extends RuntimeException {
        public enum Fate { NOT_SENT, UNKNOWN, REFUSED }

        private final Fate fate;

        public Failure(Fate fate, String message) {
            super(message);
            this.fate = fate;
        }

        public Fate fate() {
            return fate;
        }
    }
}
