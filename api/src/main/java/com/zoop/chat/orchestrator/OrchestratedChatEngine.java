package com.zoop.chat.orchestrator;

import static com.zoop.chat.orchestrator.ChatResults.InsufficientCause.*;

import com.zoop.chat.dto.ChatAppliedItem;
import com.zoop.chat.dto.ChatAppliedPeriod;
import com.zoop.chat.dto.ChatLimitation;
import com.zoop.chat.dto.ChatResult;
import com.zoop.chat.dto.ChatNotice;
import com.zoop.chat.dto.Citation;
import com.zoop.chat.executor.ChatEngine;
import com.zoop.chat.executor.ChatEngineOutcome;
import com.zoop.chat.executor.ChatJobExecutor;
import com.zoop.chat.executor.ChatRun;
import com.zoop.chat.executor.ChatRunControl;
import com.zoop.chat.orchestrator.ChatBranchContext.Branch;
import com.zoop.chat.orchestrator.ChatPlan.Mode;
import com.zoop.chat.orchestrator.ChatPlan.Planned;
import com.zoop.chat.orchestrator.ChatResults.InsufficientCause;
import com.zoop.chat.tool.ChatCapability;
import com.zoop.chat.tool.ChatToolRegistry;
import com.zoop.chat.tool.ChatToolRequest;
import com.zoop.chat.tool.ChatToolResult;
import com.zoop.chat.tool.ChatWebResult;
import com.zoop.chat.tool.ChatToolRunner;
import com.zoop.chat.tool.ChatToolUnavailable;
import com.zoop.common.json.StrictJson;
import java.time.Clock;
import java.time.Duration;
import java.time.Instant;
import java.util.ArrayList;
import java.util.HashSet;
import java.util.LinkedHashMap;
import java.util.LinkedHashSet;
import java.util.List;
import java.util.Map;
import java.util.Optional;
import java.util.Set;
import java.util.concurrent.ExecutionException;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import java.util.concurrent.Future;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.TimeoutException;
import java.util.function.Supplier;
import tools.jackson.databind.node.ArrayNode;
import tools.jackson.databind.node.ObjectNode;

/**
 * The orchestrator (AI chatbot implementation plan, stages 2 to 5; design summary 2): router → plan → stages and
 * checkpoints → generation → deterministic checks → semantic verification → result. The server decides everything a model
 * only proposes: what runs, limitations and their wording, citations, {@code answerBasis} and the outcome.
 *
 * <ul>
 * <li>Every model stage is announced through {@link ChatRunControl#beforeModelCall()} and starts only when the time left
 * covers it and every required stage after it (router 4 s, tools 10 s, generation 25 s, verification 6 s, server 3 s);
 * otherwise the run ends as {@code transient/deadline_guard} without calling it. A stage gets at most its own limit: one
 * that runs out ends as {@code response_unknown}. The executor refuses a completion past the run deadline.</li>
 * <li>A model failure is {@code transient}: {@code provider_error} (rerunnable) when nothing was processed or the answer was
 * malformed, {@code response_unknown} (never rerun) when the provider may have processed it.</li>
 * <li>A tool failure ends the run before any count is evaluated: {@code tool_timeout} and unavailable data are transient,
 * an adapter fault is internal. None of them becomes a limitation or "nothing found".</li>
 * <li>A failed deterministic check, a contradicted claim or prohibited advice is {@code validation_failed}; nothing is
 * regenerated. A section held by the verifier drops the requirements it answers as {@code evidence_insufficient}.</li>
 * <li>Limitations are recorded for the requirements the member stated; one the router only inferred is dropped silently
 * when it cannot be served. So is a concept requirement the planner split off ({@link ChatPlan.Origin#CONCEPT}): its
 * general section is answered beside its parent's result or limitation, and dropped when it breaks a general rule.</li>
 * </ul>
 *
 * <p>{@code ChatModelConfiguration} registers this engine only when the internal chat-stage client is enabled. Question
 * intake has its own flag and startup refuses to enable it without this engine; both flags are off by default.
 */
public class OrchestratedChatEngine implements ChatEngine, AutoCloseable {
    /**
     * The provisional stage limits of ZOOP-AIG-001 6.3.3 (design summary 5.1), to be re-set from measured p95. The policy's
     * router 4 s, answer 25 s and verification 6 s are the provider call timeouts the AI runtime applies; the AI service ends a
     * stage 3 s after that (its deadline per stage, for process start and ledger writes). A model stage here also covers what
     * comes outside that deadline: up to 1 s waiting for a free slot before it starts, and the reply's transport and decoding.
     * A limit equal to the service's would discard answers the service delivered in time, with their cost spent.
     * Without tools the worst case (9 + 30 + 11 + 3 = 53 s) fits the 60 s job deadline. With tools it would not (63 s): a run
     * whose router took more than 6 s ends as {@code deadline_guard} before any tool or further model call.
     */
    record StageLimits(Duration router, Duration tools, Duration generate, Duration verify, Duration server) {
        /** The AI service's slot wait (1 s) and 1 s for transport and decoding, beyond its own stage deadline. */
        static final Duration SERVICE_HEADROOM = Duration.ofSeconds(2);
        static final StageLimits POLICY = new StageLimits(Duration.ofSeconds(7).plus(SERVICE_HEADROOM), Duration.ofSeconds(10),
                Duration.ofSeconds(28).plus(SERVICE_HEADROOM), Duration.ofSeconds(9).plus(SERVICE_HEADROOM),
                Duration.ofSeconds(3));
    }
    private static final Set<String> SUPPORT = Set.of("supported", "contradicted", "hold");
    private static final Set<String> ADVICE = Set.of("no", "yes", "hold");

    private final ChatModels.Router router;
    private final ChatModels.Generator generator;
    private final ChatModels.Verifier verifier;
    private final ChatToolRegistry registry;
    private final ChatRetrieval retrieval;
    private final ChatCitationSource citations;
    private final ChatPlanner planner = new ChatPlanner();
    private final Clock clock;
    private final StageLimits limits;
    private final ExecutorService models = Executors.newVirtualThreadPerTaskExecutor();
    /** The agent path when registered (MCP endpoint on, agent enabled); null keeps every run on the direct path. */
    private final ChatAgentPath agent;
    /**
     * One agent step: the AI service's {@code chat-agent} deadline (30 s + 3 s) and the service headroom. Each step is its own
     * model call and its own guard; together they stay inside the run deadline or the run ends as {@code deadline_guard}.
     */
    static final Duration AGENT_STEP = Duration.ofSeconds(33).plus(StageLimits.SERVICE_HEADROOM);
    /** The least an agent step is given: the time to write the answer (MCP actions contract 3.2). */
    static final Duration MIN_AGENT_STEP = Duration.ofSeconds(10);
    /**
     * An agent run ends within 45 s of its start, verification and saving included (MCP actions contract 3.2), inside the
     * job's own deadline ({@link ChatJobExecutor#MAX_DEADLINE}, kept for the direct path until its stage limits are re-set
     * from measured p95: router, tools, answer and verification do not fit 45 s).
     */
    static final Duration AGENT_JOB = Duration.ofSeconds(45);
    /** All agent steps together (MCP round trips, approvals, tool calls and the final answer): at most 35 s. */
    static final Duration AGENT_TOTAL = Duration.ofSeconds(35);
    /**
     * A rerun whose job has fewer calls left than its plan needs: the same input always would, so it is not rerun and the
     * member is asked to narrow the question ({@code budget_exceeded}, chat failure contract).
     */
    static final ChatEngineOutcome.Failed TOOL_BUDGET_SPENT = new ChatEngineOutcome.Failed("budget_exceeded", null, false);

    public OrchestratedChatEngine(ChatModels.Router router, ChatModels.Generator generator, ChatModels.Verifier verifier,
            ChatToolRegistry registry, ChatToolRunner runner, ChatCitationSource citations, Clock clock) {
        this(router, generator, verifier, registry, runner, citations, clock, StageLimits.POLICY, null);
    }

    public OrchestratedChatEngine(ChatModels.Router router, ChatModels.Generator generator, ChatModels.Verifier verifier,
            ChatToolRegistry registry, ChatToolRunner runner, ChatCitationSource citations, Clock clock,
            ChatAgentPath agent) {
        this(router, generator, verifier, registry, runner, citations, clock, StageLimits.POLICY, agent);
    }

    OrchestratedChatEngine(ChatModels.Router router, ChatModels.Generator generator, ChatModels.Verifier verifier,
            ChatToolRegistry registry, ChatToolRunner runner, ChatCitationSource citations, Clock clock,
            StageLimits limits) {
        this(router, generator, verifier, registry, runner, citations, clock, limits, null);
    }

    OrchestratedChatEngine(ChatModels.Router router, ChatModels.Generator generator, ChatModels.Verifier verifier,
            ChatToolRegistry registry, ChatToolRunner runner, ChatCitationSource citations, Clock clock,
            StageLimits limits, ChatAgentPath agent) {
        this.agent = agent;
        this.limits = limits;
        this.router = router;
        this.generator = generator;
        this.verifier = verifier;
        this.registry = registry;
        this.retrieval = new ChatRetrieval(runner);
        this.citations = citations;
        this.clock = clock;
    }

    /** The run ended before a model stage because the time left could not cover what remained. */
    private static final class DeadlineGuard extends RuntimeException {
        DeadlineGuard() {
            super("deadline guard", null, false, false);
        }
    }

    /** The run ended with a classified failure. */
    private static final class Stop extends RuntimeException {
        final ChatEngineOutcome.Failed failed;

        Stop(ChatEngineOutcome.Failed failed) {
            super(failed.kind(), null, false, false);
            this.failed = failed;
        }
    }

    @Override
    public ChatEngineOutcome answer(ChatRun run, ChatRunControl control) {
        ObjectNode route = StrictJson.newObject();
        try {
            return run(run, control, route);
        } catch (DeadlineGuard guard) {
            return new ChatEngineOutcome.Failed("transient", "deadline_guard", true);
        } catch (Stop stop) {
            return stop.failed;
        } catch (ChatModels.Failure failure) {
            if (failure.fate() == ChatModels.Failure.Fate.REFUSED) return new ChatEngineOutcome.Failed("internal", null, false);
            boolean unknown = failure.fate() == ChatModels.Failure.Fate.UNKNOWN;
            return new ChatEngineOutcome.Failed("transient", unknown ? "response_unknown" : "provider_error", !unknown);
        } catch (ChatToolUnavailable unavailable) {
            return new ChatEngineOutcome.Failed("transient", null, true);
        }
    }

    private ChatEngineOutcome run(ChatRun run, ChatRunControl control, ObjectNode route) {
        Set<String> bound = registry.bound();
        ChatRouteDecision decision = model(control, limits.router(),
                limits.generate().plus(limits.verify()).plus(limits.server()),
                () -> router.route(run, bound));
        ChatPlan plan = planner.plan(run, decision, bound);
        if (plan instanceof ChatPlan.Stop stop) return stopped(run, route, stop);
        var confirmed = (ChatPlan.Run) plan;
        record(route, confirmed);

        var retrieved = new ChatRetrieval.Outcome(Map.of(), Map.of(), Set.of(), null, null);
        ChatGeneratedAnswer agentAnswer = null;
        List<String> agentNotices = List.of();
        boolean directStart = false;
        List<ChatCapability> agentTools = agentTools(confirmed);
        if (agentTools != null && !agent.available()) {
            // Preflight/circuit decisions happen before the first agent step. The direct path begins here; a failure after an
            // agent step has started is never replaced with direct results in this run. A concept question that went to
            // the agent only for its search is answered without the web, and says so.
            if (webOnly(agentTools)) agentNotices = List.of("web_unavailable");
            else directStart = true;
            agentTools = null;
            route.put("agentPreflight", "unavailable");
        }
        if (agentTools != null) {
            // The agent path: Luna chooses and chains the allowed reads, the server decides each one, and the answer is
            // checked below against exactly the results of the calls that ran (shared by the requirements they serve).
            control.phase("retrieving");
            if (control.toolCallsLeft() < 1) throw new Stop(TOOL_BUDGET_SPENT);
            // The run's deadline becomes 45 s from the job's start: verification and the final store keep to it too.
            control.shortenDeadline(run.deadline().minus(ChatJobExecutor.MAX_DEADLINE.minus(AGENT_JOB)));
            Duration after = limits.verify().plus(limits.server());
            // Luna has min(35 s, what is left of it before verification and saving): never 35 s on top.
            Duration luna = min(AGENT_TOTAL, control.remaining().minus(after));
            if (luna.compareTo(MIN_AGENT_STEP) < 0) throw new DeadlineGuard();
            Instant lunaEnd = clock.instant().plus(luna);
            ChatAgentPath.Outcome ran = agent.run(run, control, agentRequirements(confirmed), agentTools,
                    ChatAnswerCheck.MAX_CITATIONS, new ChatAgentPath.Steps() {
                        @Override
                        public ChatModels.AgentStep run(Supplier<ChatModels.AgentStep> step) {
                            // Each step waits at most what is left of the Luna budget, and never less than the time an
                            // answer needs.
                            Duration limit = min(AGENT_STEP, Duration.between(clock.instant(), lunaEnd));
                            if (limit.compareTo(MIN_AGENT_STEP) < 0) throw new DeadlineGuard();
                            return model(control, limit, after, step);
                        }

                        @Override
                        public boolean closing() {
                            // The last 10 s write the answer: no new tool starts in them.
                            return Duration.between(clock.instant(), lunaEnd).compareTo(MIN_AGENT_STEP.multipliedBy(2)) < 0;
                        }
                    });
            Map<String, List<ChatToolResult>> results = new LinkedHashMap<>();
            confirmed.requirements().stream().filter(p -> p.mode() == Mode.TOOLS)
                    .forEach(p -> results.put(p.id(), ran.results()));
            // A concept part may rest on the run's web hits (Q02's first support), never on its internal reads.
            List<ChatToolResult> web = ran.results().stream().filter(r -> !r.webResults().isEmpty()).toList();
            if (!web.isEmpty()) {
                confirmed.requirements().stream().filter(p -> p.mode() == Mode.GENERAL)
                        .forEach(p -> results.put(p.id(), web));
            }
            retrieved = new ChatRetrieval.Outcome(results, Map.of(), Set.of(), null, null);
            agentAnswer = ran.answer();
            agentNotices = ran.notices();
            route.put("path", "agent").put("agentSteps", ran.steps()).put("approvedCalls", ran.approved())
                    .put("deniedCalls", ran.denied());
        } else if (confirmed.requirements().stream().anyMatch(p -> p.mode() == Mode.TOOLS)) {
            // Every run that reads says which path read it; agentPreflight says when the agent was a candidate but not ready.
            route.put("path", "direct");
            control.phase("retrieving");
            // A rerun reads within what is left of the job's calls, never a new budget.
            if (ChatPlanner.worstCaseCalls(confirmed) > control.toolCallsLeft()) throw new Stop(TOOL_BUDGET_SPENT);
            guard(control, limits.tools().plus(limits.generate()).plus(limits.verify()).plus(limits.server()));
            retrieved = retrieval.run(run, control, confirmed);
            if (retrieved.failed() != null) throw new Stop(toolFailure(retrieved.failed()));
            if (retrieved.stop() != null) return stopped(run, route, retrieved.stop());
            if (retrieved.faulted() != null) {
                route.putArray("toolFaults").addAll(strings(retrieved.limitations().entrySet().stream()
                        .filter(e -> ChatRetrieval.TOOL_UNAVAILABLE.equals(e.getValue())).map(Map.Entry::getKey).toList()));
            }
        }

        Map<String, Planned> byId = new LinkedHashMap<>();
        confirmed.requirements().forEach(p -> byId.put(p.id(), p));
        Map<String, String> limited = new LinkedHashMap<>();
        confirmed.requirements().stream().filter(p -> p.mode() == Mode.LIMITED).forEach(p -> limited.put(p.id(), p.limitation()));
        limited.putAll(retrieved.limitations());
        List<Branch> branches = new ArrayList<>();
        for (Planned p : confirmed.requirements()) {
            // A member-scope source is no branch: its companies go with the requirement it serves.
            if (p.mode() == Mode.LIMITED || limited.containsKey(p.id()) || p.origin() == ChatPlan.Origin.SCOPE) continue;
            List<String> avoid = p.parent() == null ? List.of()
                    : labels(retrieved.results().getOrDefault(p.parent(), List.of()));
            List<ChatToolResult> results = new ArrayList<>();
            if (p.onScope()) results.addAll(retrieved.results().getOrDefault(p.dependsOn().requirementId(), List.of()));
            results.addAll(retrieved.results().getOrDefault(p.id(), List.of()));
            branches.add(new Branch(p.id(), p.label(), p.types(), p.mode() == Mode.GENERAL, results,
                    retrieved.noneFound().contains(p.id()), p.parent(), avoid));
        }
        route.set("limited", json(limited));
        // A fault that leaves nothing answered is the job's failure, never hidden as missing evidence.
        if (branches.isEmpty() && retrieved.faulted() != null) throw new Stop(toolFailure(retrieved.faulted()));
        if (branches.isEmpty()) {
            boolean unanswerable = limited.values().stream().allMatch(k -> k.equals("investment_advice") || k.equals("out_of_scope"));
            if (unanswerable) {
                return stopped(run, route, new ChatPlan.Stop("guidance",
                        limited.containsValue("investment_advice") ? "investment_advice" : "out_of_scope", List.of()));
            }
            return insufficient(run, route, limited.containsValue("results_truncated") ? RESULTS_TRUNCATED
                    : limited.containsValue("not_in_member_scope") ? NOT_IN_MEMBER_SCOPE
                    : limited.containsValue("precondition_unmet") ? PRECONDITION_UNMET : EVIDENCE_INSUFFICIENT,
                    confirmed, retrieved);
        }

        ChatGeneratedAnswer generated;
        if (agentAnswer != null) {
            generated = agentAnswer;
        } else {
            control.phase("writing");
            var context = new ChatBranchContext(run.turns(), run.context(), branches, ChatAnswerCheck.MAX_CITATIONS);
            generated = model(control, limits.generate(), limits.verify().plus(limits.server()),
                    () -> generator.generate(run, context));
        }
        var checked = ChatAnswerCheck.check(branches, generated);
        route.put("deterministicCheck", checked.failedCheck() == null ? "passed" : checked.failedCheck());
        if (checked.failedCheck() != null) return validationFailed();
        var passed = checked.passed();
        if (!passed.dropped().isEmpty()) route.putArray("droppedGeneral").addAll(strings(passed.dropped()));

        Map<String, ChatWebResult> hits = new LinkedHashMap<>();
        branches.forEach(b -> b.results().forEach(r -> r.webResults().forEach(h -> hits.putIfAbsent(h.id(), h))));
        Map<String, Citation> cited = new LinkedHashMap<>();
        for (var section : passed.sections()) {
            for (String id : section.evidenceIds()) {
                Citation citation = cited.get(id);
                if (citation == null) {
                    // A web hit is cited as the search returned it: there is no evidence record to read again.
                    Optional<Citation> read = hits.containsKey(id) ? Optional.of(webCitation(hits.get(id)))
                            : citations.cite(id, run.graphVersionId(), run.context().asOf(), run.jobId());
                    // Readable when the tool passed it on and not now: the answer cannot stand on it.
                    if (read.isEmpty()) return validationFailed();
                    citation = read.get();
                    cited.put(id, citation);
                }
                // A ZOOP document section quotes ZOOP documents only, a web section web hits only, and no other section
                // quotes either.
                if ("zoop_documented".equals(section.basis()) != "zoop_doc".equals(citation.sourceKind())
                        || "web_reported".equals(section.basis()) != "web_result".equals(citation.sourceKind())) {
                    return validationFailed();
                }
            }
        }

        control.phase("verifying");
        List<Citation> allCited = List.copyOf(cited.values());
        ChatModels.ServerFacts facts = ChatModels.ServerFacts.capture(run, passed.sections(), branches);
        ChatSemanticVerdicts verdicts = model(control, limits.verify(), limits.server(),
                () -> verifier.verify(run, passed.sections(), allCited, facts));
        Set<String> held = held(passed.sections(), verdicts);
        if (held == null) return validationFailed();
        route.putArray("heldRequirements").addAll(strings(held));

        List<ChatGeneratedAnswer.Section> kept = passed.sections().stream()
                .filter(s -> s.requirementIds().stream().noneMatch(held::contains)).toList();
        Set<String> insufficient = new LinkedHashSet<>(passed.insufficient());
        passed.sections().stream().filter(s -> !kept.contains(s)).forEach(s -> insufficient.addAll(s.requirementIds()));
        // A requirement still answered by a kept section of its own is answered; a joining section goes with any held part.
        insufficient.removeIf(id -> kept.stream().anyMatch(s -> s.requirementIds().contains(id)));
        if (kept.isEmpty() && retrieved.faulted() != null) throw new Stop(toolFailure(retrieved.faulted()));
        if (kept.isEmpty()) {
            // The most specific cause the server knows: a limit it hit, then a verdict, then a lookup that found nothing.
            List<String> unanswered = insufficient.stream().filter(id -> byId.get(id).parent() == null).toList();
            InsufficientCause cause = limited.containsValue("results_truncated") ? RESULTS_TRUNCATED
                    : limited.containsValue("not_in_member_scope") ? NOT_IN_MEMBER_SCOPE
                    : unanswered.stream().anyMatch(held::contains) ? EVIDENCE_HELD
                    : !unanswered.isEmpty() && retrieved.noneFound().containsAll(unanswered) ? NOTHING_FOUND
                    : limited.containsValue("precondition_unmet") ? PRECONDITION_UNMET : EVIDENCE_INSUFFICIENT;
            return insufficient(run, route, cause, confirmed, retrieved);
        }

        Set<String> keptEvidence = new HashSet<>();
        kept.forEach(s -> keptEvidence.addAll(s.evidenceIds()));
        List<Citation> keptCitations = cited.values().stream().filter(c -> keptEvidence.contains(c.evidenceId())).toList();
        List<ChatLimitation> limitations = new ArrayList<>();
        for (var entry : limited.entrySet()) {
            Planned p = byId.get(entry.getKey());
            if (explicit(decision, p.id())) limitations.add(ChatResults.limitation(entry.getValue(), p.label()));
        }
        for (String id : insufficient) {
            if (!explicit(decision, id)) continue;
            InsufficientCause cause = held.contains(id) ? EVIDENCE_HELD
                    : retrieved.noneFound().contains(id) ? NOTHING_FOUND : EVIDENCE_INSUFFICIENT;
            limitations.add(ChatResults.insufficient(cause, byId.get(id).label()));
        }
        for (String id : retrieved.cut()) {
            // Answered on only the first of the member's companies: say so beside the answer.
            if (explicit(decision, id) && kept.stream().anyMatch(s -> s.requirementIds().contains(id))) {
                limitations.add(ChatResults.scopeCut(byId.get(id).label()));
            }
        }
        // A reference point outside the member's companies was read all the same: the only note that leaves nothing
        // unanswered, so it alone does not make the answer partial.
        int anchorNotes = 0;
        for (var entry : retrieved.outside().entrySet()) {
            String id = entry.getKey();
            // Answered on the member's companies, though the question also named one that is not: say so beside it.
            if (explicit(decision, id) && kept.stream().anyMatch(s -> s.requirementIds().contains(id))) {
                limitations.add(ChatResults.outsideScope(entry.getValue(), byId.get(id).label()));
                if (entry.getValue() == ChatRetrieval.Outside.ANCHOR) anchorNotes++;
            }
        }
        boolean partial = limitations.size() > anchorNotes;

        Set<String> answered = new HashSet<>();
        kept.forEach(s -> answered.addAll(s.requirementIds()));
        // A map target stays only while a requirement whose tools returned it is still answered.
        Set<String> reachable = new HashSet<>();
        branches.stream().filter(b -> answered.contains(b.requirementId()))
                .forEach(b -> b.results().forEach(r -> r.items().forEach(i -> reachable.add(i.id()))));
        var targets = passed.graphTargets().stream().filter(g -> reachable.contains(g.id())).toList();
        ChatResult result = ChatResults.answered(run, kept, keptCitations, targets,
                items(retrieved, answered, "company"), items(retrieved, answered, "issue"), limitations, partial,
                notices(directStart, agentNotices), overrode(run, confirmed, answered),
                writtenPeriod(run, confirmed, answered), clock.instant());
        route.put("outcome", "answered");
        return new ChatEngineOutcome.Completed(result, route);
    }

    /**
     * Nothing could be answered: the reason says why and what to try, and {@code applied} shows what the reads looked at
     * (every requirement's, since none was answered).
     */
    private ChatEngineOutcome insufficient(ChatRun run, ObjectNode route, InsufficientCause cause, ChatPlan.Run plan,
            ChatRetrieval.Outcome retrieved) {
        route.put("outcome", "insufficient_evidence").put("reason", cause.code());
        Set<String> all = new HashSet<>();
        plan.requirements().forEach(p -> all.add(p.id()));
        return new ChatEngineOutcome.Completed(ChatResults.insufficient(run, cause, narrowed(plan, retrieved),
                items(retrieved, all, "company"), items(retrieved, all, "issue"), overrode(run, plan, all), clock.instant()),
                route);
    }

    /**
     * Whether every read that ran was bound to the selected evidence: some requirement read, and each one that did had an
     * evidence scope. A mix of narrowed and wide reads is not narrowed.
     */
    static boolean narrowed(ChatPlan.Run plan, ChatRetrieval.Outcome retrieved) {
        List<Planned> read = plan.requirements().stream()
                .filter(p -> p.mode() == Mode.TOOLS && retrieved.results().containsKey(p.id())).toList();
        return !read.isEmpty() && read.stream().allMatch(p -> p.evidenceScope() != null);
    }

    /** The items of one kind the reads of these requirements returned, once each, in read order. */
    private static List<ChatAppliedItem> items(ChatRetrieval.Outcome retrieved, Set<String> requirements, String kind) {
        Map<String, ChatAppliedItem> items = new LinkedHashMap<>();
        retrieved.results().forEach((requirement, results) -> {
            if (!requirements.contains(requirement)) return;
            results.forEach(r -> r.items().stream().filter(i -> kind.equals(i.kind()))
                    .forEach(i -> items.putIfAbsent(i.id(), new ChatAppliedItem(i.id(), i.label()))));
        });
        return List.copyOf(items.values());
    }

    /**
     * The period an answered comparison read from the question's own words or carried from the last answers, or null when
     * none did; a selected period is applied on its own.
     */
    private static ChatAppliedPeriod writtenPeriod(ChatRun run, ChatPlan.Run plan, Set<String> answered) {
        for (Planned p : plan.requirements()) {
            if (!answered.contains(p.id()) || !p.capabilities().contains(ChatCapability.GRAPH_VERSION_DIFF)) continue;
            var period = ChatRetrieval.period(run, p).filter(found -> found.expression() != null || run.context().period() == null);
            if (period.isPresent()) {
                return new ChatAppliedPeriod(period.get().start().toString(), period.get().end().toString(),
                        period.get().expression() != null ? "question" : "context", period.get().expression());
            }
        }
        return null;
    }

    /** The question replaced the selection when one of these requirements read targets the member had not selected. */
    private static boolean overrode(ChatRun run, ChatPlan.Run plan, Set<String> requirements) {
        Set<String> selected = Set.copyOf(run.selection().contextIds());
        return !selected.isEmpty() && plan.requirements().stream()
                .anyMatch(p -> requirements.contains(p.id()) && p.targetSource() == ChatPlan.TargetSource.QUESTION
                        && !selected.containsAll(p.targets()));
    }

    /**
     * The requirements the verdicts hold back, or null when a section is contradicted or gives prohibited advice. A verdict
     * list that does not match the sections is a malformed answer.
     */
    private static Set<String> held(List<ChatGeneratedAnswer.Section> sections, ChatSemanticVerdicts verdicts) {
        if (verdicts.sections().size() != sections.size()) throw malformedVerdicts();
        Set<String> held = new LinkedHashSet<>();
        for (int i = 0; i < sections.size(); i++) {
            var section = sections.get(i);
            var verdict = verdicts.sections().get(i);
            boolean general = "general_knowledge".equals(section.basis());
            if (!ADVICE.contains(verdict.prohibitedAdvice())
                    || (general ? verdict.support() != null : !SUPPORT.contains(verdict.support()))) {
                throw malformedVerdicts();
            }
            if ("yes".equals(verdict.prohibitedAdvice()) || "contradicted".equals(verdict.support())) return null;
            if ("hold".equals(verdict.prohibitedAdvice()) || "hold".equals(verdict.support())) {
                held.addAll(section.requirementIds());
            }
        }
        return held;
    }

    private static ChatModels.Failure malformedVerdicts() {
        return new ChatModels.Failure(ChatModels.Failure.Fate.NOT_SENT, "verdicts do not match the sections");
    }

    /**
     * One model stage: it starts only when the time left covers it and what follows, is announced before it is sent, and
     * gets at most its own limit. A stage that runs out is interrupted and ends as a response of unknown fate: the provider
     * may have processed it, so it is never rerun and its late answer never becomes a result.
     */
    private <T> T model(ChatRunControl control, Duration stage, Duration after, Supplier<T> call) {
        guard(control, stage.plus(after));
        control.beforeModelCall();
        Future<T> pending = models.submit(call::get);
        try {
            return pending.get(stage.toNanos(), TimeUnit.NANOSECONDS);
        } catch (TimeoutException late) {
            pending.cancel(true);
            throw new ChatModels.Failure(ChatModels.Failure.Fate.UNKNOWN, "model stage ran past its limit");
        } catch (InterruptedException interrupted) {
            pending.cancel(true);
            Thread.currentThread().interrupt();
            throw new ChatModels.Failure(ChatModels.Failure.Fate.UNKNOWN, "interrupted while waiting for a model");
        } catch (ExecutionException failed) {
            if (failed.getCause() instanceof RuntimeException runtime) throw runtime;
            throw new IllegalStateException("model stage failed", failed.getCause());
        }
    }

    @Override
    public void close() {
        models.shutdownNow();
    }

    /**
     * The tools of the agent path for this plan, or null for the direct path. The agent takes a plan whose reads are all
     * independent first-stage reads the MCP endpoint exposes: no member-scope read or dependent stage (Q07 and checkpointed
     * plans stay direct, the member scope being a server-only precondition), no requirement over the fan-out of one call
     * ({@link ChatToolRequest#MAX_TARGETS} targets: the server batches those itself, MCP actions contract 3.2) and at least one
     * read at all (a plan of general and limited requirements needs no tools).
     */
    List<ChatCapability> agentTools(ChatPlan.Run plan) {
        if (agent == null) return null;
        Set<ChatCapability> exposed = agent.tools();
        Set<ChatCapability> tools = new LinkedHashSet<>();
        for (Planned p : plan.requirements()) {
            if (p.mode() != Mode.TOOLS) continue;
            if (p.origin() == ChatPlan.Origin.SCOPE || p.dependsOn() != null || p.stage() != 1
                    || p.targets().size() > ChatToolRequest.MAX_TARGETS || !exposed.containsAll(p.capabilities())) {
                return null;
            }
            tools.addAll(p.capabilities());
        }
        // The web (web search design 1) is the first support of a concept (Q02: one search, tried by default) and the last
        // resort of a fact question (Q03~Q08: approved only once the internal reads left something unmet). A question
        // with a service-rule part (Q01) is never offered it: its answer may not rest on the web, and a search cannot yet
        // be tied to the part it serves.
        boolean concept = plan.requirements().stream().anyMatch(p -> p.mode() == Mode.GENERAL);
        boolean fact = plan.requirements().stream().anyMatch(p -> p.mode() == Mode.TOOLS
                && p.types().stream().anyMatch(WEB_TYPES::contains));
        boolean rules = plan.requirements().stream().anyMatch(p -> p.types().contains(ChatQueryType.Q01));
        if ((concept || fact) && !rules && exposed.contains(ChatCapability.WEB_SEARCH)) {
            // A concept question with no read of its own goes to the agent for its search alone.
            tools.add(ChatCapability.WEB_SEARCH);
        }
        return tools.isEmpty() ? null : List.copyOf(tools);
    }

    /** Whether the agent was offered nothing but the web: a concept question with no read of its own. */
    private static boolean webOnly(List<ChatCapability> tools) {
        return tools != null && tools.equals(List.of(ChatCapability.WEB_SEARCH));
    }

    /**
     * The public citation of a web hit (web search design 6): its server id, snippet, title, domain as publisher, provider
     * as {@code docId}, publication time and URL. It is no ZOOP evidence and never becomes one.
     */
    static Citation webCitation(ChatWebResult hit) {
        return new Citation("web_result", hit.id(), hit.snippet(), null, null, hit.provider(), null, 0,
                hit.snippet().codePointCount(0, hit.snippet().length()), hit.title(), hit.domain(), hit.publishedAt(),
                hit.url());
    }

    /** What the answer went on without: a direct start, and the web faults of an agent run. */
    private static List<ChatNotice> notices(boolean directStart, List<String> agentNotices) {
        List<ChatNotice> notices = new ArrayList<>();
        if (directStart) notices.add(ChatResults.notice("mcp_direct_start"));
        agentNotices.forEach(code -> notices.add(ChatResults.notice(code)));
        return notices;
    }

    /** The question types whose unmet requirements may fall back on the web (web search design 1). */
    private static final Set<ChatQueryType> WEB_TYPES = Set.of(ChatQueryType.Q03, ChatQueryType.Q04, ChatQueryType.Q05,
            ChatQueryType.Q06, ChatQueryType.Q07, ChatQueryType.Q08);

    /** The answerable requirements of the plan as the agent sees them: reads with their resolved targets, general parts. */
    private static List<ChatModels.AgentRequirement> agentRequirements(ChatPlan.Run plan) {
        return plan.requirements().stream().filter(p -> p.mode() == Mode.TOOLS || p.mode() == Mode.GENERAL)
                .map(p -> new ChatModels.AgentRequirement(p.id(), p.label(), p.mode() == Mode.GENERAL,
                        p.mode() == Mode.TOOLS ? p.targets() : List.of()))
                .toList();
    }

    private static Duration min(Duration a, Duration b) {
        return a.compareTo(b) <= 0 ? a : b;
    }

    private static void guard(ChatRunControl control, Duration needed) {
        if (control.remaining().compareTo(needed) < 0) throw new DeadlineGuard();
    }

    private static ChatEngineOutcome.Failed toolFailure(ChatToolResult failed) {
        return switch (failed.error()) {
            case ChatToolRunner.TIMEOUT -> new ChatEngineOutcome.Failed("transient", "tool_timeout", true);
            case ChatToolRunner.UNAVAILABLE -> new ChatEngineOutcome.Failed("transient", null, true);
            default -> new ChatEngineOutcome.Failed("internal", null, false);
        };
    }

    private static ChatEngineOutcome validationFailed() {
        return new ChatEngineOutcome.Failed("validation_failed", null, false);
    }

    private ChatEngineOutcome stopped(ChatRun run, ObjectNode route, ChatPlan.Stop stop) {
        route.put("outcome", stop.outcome()).put("reason", stop.reason());
        return new ChatEngineOutcome.Completed(
                ChatResults.withoutAnswer(run, stop.outcome(), stop.reason(), stop.choices(), clock.instant()), route);
    }

    private static boolean explicit(ChatRouteDecision decision, String id) {
        return decision.requirements().stream().anyMatch(r -> r.id().equals(id) && r.explicit());
    }

    /** The route summary keeps decisions only: requirement modes, capabilities and stages, never model reasoning. */
    private static void record(ObjectNode route, ChatPlan.Run plan) {
        ArrayNode requirements = route.putArray("requirements");
        for (Planned p : plan.requirements()) {
            ObjectNode node = requirements.addObject().put("id", p.id()).put("mode", p.mode().name().toLowerCase())
                    .put("stage", p.stage());
            node.putArray("types").addAll(strings(p.types().stream().map(Enum::name).sorted().toList()));
            node.putArray("capabilities").addAll(strings(p.capabilities().stream().map(c -> c.id()).toList()));
            if (p.limitation() != null) node.put("limitation", p.limitation());
            if (p.parent() != null) node.put("origin", p.origin().name().toLowerCase()).put("parent", p.parent());
        }
    }

    /** The company and issue labels a requirement's reads returned. */
    private static List<String> labels(List<ChatToolResult> results) {
        Set<String> labels = new LinkedHashSet<>();
        results.forEach(r -> r.items().stream().filter(i -> "company".equals(i.kind()) || "issue".equals(i.kind()))
                .forEach(i -> labels.add(i.label())));
        return List.copyOf(labels);
    }

    private static ArrayNode strings(Iterable<String> values) {
        ArrayNode array = StrictJson.newArray();
        values.forEach(array::add);
        return array;
    }

    private static ObjectNode json(Map<String, String> values) {
        ObjectNode node = StrictJson.newObject();
        values.forEach(node::put);
        return node;
    }
}
