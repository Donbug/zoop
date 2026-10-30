package com.zoop.chat.orchestrator;

import com.zoop.chat.dto.Citation;
import com.zoop.chat.executor.ChatRun;
import com.zoop.chat.tool.ChatCapability;
import com.zoop.chat.tool.ChatToolItem;
import com.zoop.chat.tool.ChatToolRequest;
import com.zoop.chat.tool.ChatToolResult;
import java.time.Instant;
import java.util.ArrayList;
import java.util.HashSet;
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
        ChatSemanticVerdicts verify(ChatRun run, List<ChatGeneratedAnswer.Section> sections, List<Citation> citations,
                ServerFacts facts);
    }

    /** Canonical facts are server observations, not article evidence and never a model's assertions. */
    public sealed interface ServerFact permits PortfolioFact, ComparisonFact {
        String requirementId();
    }

    public record MemberCompany(String companyId, String name, boolean held, boolean watched) { }

    public record PortfolioFact(String requirementId, String queryScope, List<String> companyIds,
            List<MemberCompany> companies, boolean truncated, int companyLimit) implements ServerFact { }

    public record GraphChange(String id, String kind, String name, String change) { }

    public record ComparisonFact(String requirementId, String fromVersion, String toVersion, Instant asOf,
            Instant since, String queryScope, List<String> targetIds, int evidenceLimit, int changeLimit,
            boolean evidenceRestricted, List<GraphChange> changes, boolean truncated) implements ServerFact { }

    /**
     * A short-lived, non-deserializable envelope captured from current branches, consumed with the exact run and checked
     * sections. Scope reads merged into their parent stay attached to it; no membership query is repeated.
     */
    public static final class ServerFacts {
        private final ChatRun owner;
        private final List<ChatGeneratedAnswer.Section> sections;
        private final List<List<ServerFact>> bySection;

        private ServerFacts(ChatRun owner, List<ChatGeneratedAnswer.Section> sections, List<List<ServerFact>> bySection) {
            this.owner = owner;
            this.sections = List.copyOf(sections);
            this.bySection = List.copyOf(bySection);
        }

        public static ServerFacts withoutTools(ChatRun run, List<ChatGeneratedAnswer.Section> sections) {
            return new ServerFacts(run, sections, sections.stream().map(s -> List.<ServerFact>of()).toList());
        }

        public List<List<ServerFact>> forRequest(ChatRun run, List<ChatGeneratedAnswer.Section> checked) {
            if (owner != run || !sections.equals(checked)) throw invalidFacts();
            return bySection;
        }

        static ServerFacts capture(ChatRun run, List<ChatGeneratedAnswer.Section> sections,
                List<ChatBranchContext.Branch> branches) {
            List<List<ServerFact>> all = new ArrayList<>();
            for (var section : sections) {
                List<ServerFact> facts = new ArrayList<>();
                for (var branch : branches) {
                    if (!"evidence_grounded".equals(section.basis())
                            || !section.requirementIds().contains(branch.requirementId()) || branch.general()) continue;
                    Set<String> seen = new HashSet<>();
                    for (var result : branch.results()) {
                        boolean portfolio = ChatCapability.PORTFOLIO_SCOPE_READ.id().equals(result.capabilityId());
                        boolean comparison = ChatCapability.GRAPH_VERSION_DIFF.id().equals(result.capabilityId());
                        if (!portfolio && !comparison) continue;
                        if (!result.succeeded() || result.provenance() == null
                                || !result.provenance().belongsTo(run)) throw invalidFacts();
                        ChatToolRequest query = result.provenance().request();
                        if (!query.capabilityId().equals(result.capabilityId()) || result.truncated() == null
                                || !seen.add(result.toolCallId())) throw invalidFacts();
                        ServerFact fact = portfolio ? portfolio(branch.requirementId(), result, query)
                                : comparison(run, branch.requirementId(), result, query);
                        // No baseline is not a comparison and therefore supplies no facts; an identical read adds nothing.
                        if (fact != null && !facts.contains(fact)) facts.add(fact);
                    }
                }
                if (facts.size() > 72) throw invalidFacts();
                all.add(List.copyOf(facts));
            }
            return new ServerFacts(run, sections, all);
        }

        private static PortfolioFact portfolio(String requirement, ChatToolResult result, ChatToolRequest query) {
            if (!"member-scope".equals(result.dataVersion()) || result.items().size() > ChatToolRequest.MAX_TARGETS) {
                throw invalidFacts();
            }
            boolean whole = query.targets().equals(List.of(ChatCapability.MEMBER_SELF));
            List<String> targets = whole ? List.of() : query.targets();
            if (targets.stream().anyMatch(id -> !companyId(id))) throw invalidFacts();
            List<MemberCompany> companies = new ArrayList<>();
            for (ChatToolItem item : result.items()) {
                if (!"company".equals(item.kind()) || !companyId(item.id())) throw invalidFacts();
                String suffix;
                boolean held;
                boolean watched;
                if (item.label().endsWith(" (보유·관심)")) {
                    suffix = " (보유·관심)"; held = true; watched = true;
                } else if (item.label().endsWith(" (보유)")) {
                    suffix = " (보유)"; held = true; watched = false;
                } else if (item.label().endsWith(" (관심)")) {
                    suffix = " (관심)"; held = false; watched = true;
                } else {
                    throw invalidFacts();
                }
                if (!whole && !targets.contains(item.id())) throw invalidFacts();
                companies.add(new MemberCompany(item.id(), bounded(item.label().substring(0,
                        item.label().length() - suffix.length())), held, watched));
            }
            return new PortfolioFact(requirement, whole ? "current_member" : "named_companies", targets,
                    List.copyOf(companies), result.truncated(), ChatToolRequest.MAX_TARGETS);
        }

        private static ComparisonFact comparison(ChatRun run, String requirement, ChatToolResult result,
                ChatToolRequest query) {
            String version = result.dataVersion();
            if (version == null || run.graphVersionId() == null) throw invalidFacts();
            String suffix = ".." + run.graphVersionId();
            if (!version.endsWith(suffix)) {
                if (version.equals(run.graphVersionId()) && result.truncated() && result.items().isEmpty()) return null;
                throw invalidFacts();
            }
            String earlier = version.substring(0, version.length() - suffix.length());
            if (earlier.isBlank() || earlier.length() > 200 || result.items().size() > 40) throw invalidFacts();
            List<String> targets = query.targets().stream().filter(id -> !id.startsWith("ev-")).toList();
            boolean whole = targets.isEmpty() || targets.equals(List.of(ChatCapability.WHOLE_GRAPH));
            if (!whole && targets.stream().anyMatch(id -> id.startsWith("member:") || id.equals(ChatCapability.WHOLE_GRAPH))) {
                throw invalidFacts();
            }
            List<GraphChange> changes = new ArrayList<>();
            for (ChatToolItem item : result.items()) {
                if (!Set.of("company", "issue", "edge").contains(item.kind())) throw invalidFacts();
                String prefix = item.label().startsWith("[새로 생김] ") ? "[새로 생김] "
                        : item.label().startsWith("[사라짐] ") ? "[사라짐] " : null;
                if (prefix == null) throw invalidFacts();
                String name = item.label().substring(prefix.length());
                if (name.codePointCount(0, name.length()) > 300) {
                    name = name.substring(0, name.offsetByCodePoints(0, 299)) + "…";
                }
                changes.add(new GraphChange(item.id(), item.kind(), bounded(name),
                        prefix.equals("[새로 생김] ") ? "added" : "removed"));
            }
            return new ComparisonFact(requirement, earlier, run.graphVersionId(), run.context().asOf(), query.since(),
                    whole ? "whole_graph" : "targets", whole ? List.of() : targets, query.limit(), 40,
                    query.evidenceScope() != null, List.copyOf(changes), result.truncated());
        }

        private static boolean companyId(String id) {
            return id != null && id.length() <= 200 && id.indexOf(':') > 0 && !id.startsWith("member:");
        }

        private static String bounded(String name) {
            if (name.isBlank() || name.codePointCount(0, name.length()) > 300) throw invalidFacts();
            return name;
        }

        private static Failure invalidFacts() {
            return new Failure(Failure.Fate.REFUSED, "server facts do not belong to the checked request");
        }
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
     * What one agent step sends: the requirements, the run's grant token, the tools the run may use, the recipient the MCP
     * results' send grants are checked for (the AI runtime sends the step only when that is its own recipient) and, for a
     * continuation, the stored response and the server's decisions on it. The MCP server's URL is no part of it: the AI
     * runtime sends grants only to its operator's configured server ({@code ZOOP_AI_CHAT_MCP_SERVER_URL}).
     */
    public record AgentInput(List<AgentRequirement> requirements, String grantToken, List<String> allowedTools,
            String recipient, int maxCitations, String previousResponseId, List<Decision> decisions) {
        public AgentInput {
            if (recipient == null || recipient.isBlank()) throw new IllegalArgumentException("a step names its recipient");
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
        private final String code;

        public Failure(Fate fate, String message) {
            this(fate, null, message);
        }

        public Failure(Fate fate, String code, String message) {
            super(message);
            this.fate = fate;
            this.code = code;
        }

        public Fate fate() {
            return fate;
        }

        /** The stable AI runtime failure code, when the failure came from a stage outcome. */
        public String code() {
            return code;
        }
    }
}
