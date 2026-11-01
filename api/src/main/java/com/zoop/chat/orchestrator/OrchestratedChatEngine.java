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
import java.util.Collections;
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
 * <li>A tool failure leaving nothing answered ends the run before any count is evaluated: {@code tool_timeout} and unavailable
 * data are transient, an adapter fault is internal. None of them becomes "nothing found". A requirement answered on the rest
 * of its reads says so in a {@code tool_unavailable} notice; one left unanswered is that limitation.</li>
 * <li>A failed deterministic check, a contradicted claim or prohibited advice is {@code validation_failed}; nothing is
 * regenerated. A section held by the verifier drops the requirements it answers as {@code evidence_insufficient}.</li>
 * <li>Each requirement's end is the server's own record ({@link ChatRequirementCoverage}, in the route summary): an answer
 * leaving one undecided is {@code validation_failed}.</li>
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
     * The values remain per-stage ceilings, not time reservations. Direct stages shrink to the time left after the minimum
     * answer, verification and terminal-write reservations below, so every route remains inside the 45 s job deadline.
     */
    record StageLimits(Duration router, Duration tools, Duration generate, Duration verify, Duration server) {
        /** The AI service's slot wait (1 s) and 1 s for transport and decoding, beyond its own stage deadline. */
        static final Duration SERVICE_HEADROOM = Duration.ofSeconds(2);
        static final StageLimits POLICY = new StageLimits(Duration.ofSeconds(7).plus(SERVICE_HEADROOM), Duration.ofSeconds(10),
                Duration.ofSeconds(28).plus(SERVICE_HEADROOM), Duration.ofSeconds(9).plus(SERVICE_HEADROOM),
                Duration.ofSeconds(3));
    }
    /** Minimum direct answer window kept after reads (and after an optional search-only step). */
    static final Duration MIN_DIRECT_GENERATE = Duration.ofSeconds(10);
    /** Minimum semantic-verification window kept before the terminal write. */
    static final Duration MIN_VERIFY = Duration.ofSeconds(6);
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
     * An agent run ends within 45 s of its start, verification and saving included (MCP actions contract 3.2). This equals
     * the job-wide deadline and remains named here because the agent budget is part of the external execution contract.
     */
    static final Duration AGENT_JOB = Duration.ofSeconds(45);
    /** All agent steps together (MCP round trips, approvals, tool calls and the final answer): at most 35 s. */
    static final Duration AGENT_TOTAL = Duration.ofSeconds(35);
    /** The web search after the server's own reads: at most this, and never the time the answer still needs. */
    static final Duration WEB_AFTER_READS = Duration.ofSeconds(20);
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
            // The same question would meet the same limit: the member narrows it instead of rerunning it.
            if (ChatModels.INPUT_BUDGET_EXCEEDED.equals(failure.code())) {
                return new ChatEngineOutcome.Failed("budget_exceeded", "context_too_large", false);
            }
            if (ChatModels.OUTPUT_BUDGET_EXCEEDED.equals(failure.code())) {
                return new ChatEngineOutcome.Failed("budget_exceeded", "output_limit", false);
            }
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
                limits.tools().plus(MIN_DIRECT_GENERATE).plus(MIN_VERIFY).plus(limits.server()),
                () -> router.route(run, bound));
        ChatPlan plan = planner.plan(run, decision, bound);
        var coverage = new ChatRequirementCoverage(decision);
        if (plan instanceof ChatPlan.Stop stop) return stopped(run, route, stop, coverage);
        var confirmed = (ChatPlan.Run) plan;
        record(route, confirmed);
        coverage.plan(confirmed);

        var retrieved = new ChatRetrieval.Outcome(Map.of(), Map.of(), Set.of(), null, null);
        ChatGeneratedAnswer agentAnswer = null;
        List<String> agentNotices = List.of();
        boolean directStart = false;
        List<ChatCapability> agentTools = agentTools(run, confirmed);
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
            // checked below against exactly the results of the calls that ran, each requirement against its own.
            control.phase("retrieving");
            if (control.toolCallsLeft() < 1) throw new Stop(TOOL_BUDGET_SPENT);
            // Idempotently keep the agent path on the same 45 s deadline as every other route.
            control.shortenDeadline(run.deadline().minus(ChatJobExecutor.MAX_DEADLINE.minus(AGENT_JOB)));
            Duration after = MIN_VERIFY.plus(limits.server());
            // Luna has min(35 s, what is left of it before verification and saving): never 35 s on top.
            Duration luna = min(AGENT_TOTAL, control.remaining().minus(after));
            if (luna.compareTo(MIN_AGENT_STEP) < 0) throw new DeadlineGuard();
            ChatAgentPath.Outcome ran = agent.run(run, control, agentRequirements(confirmed), agentTools,
                    // The last 10 s write the answer: no new tool starts in them.
                    ChatAnswerCheck.MAX_CITATIONS, steps(control, clock.instant().plus(luna), after,
                            MIN_AGENT_STEP.multipliedBy(2)));
            Map<String, List<ChatToolResult>> results = new LinkedHashMap<>();
            confirmed.requirements().stream().filter(p -> p.mode() == Mode.TOOLS)
                    .forEach(p -> results.put(p.id(), ran.resultsOf(p.id())));
            // A concept part may rest on its web hits (Q02's first support), never on internal reads.
            confirmed.requirements().stream().filter(p -> p.mode() == Mode.GENERAL).forEach(p -> {
                List<ChatToolResult> web = ran.resultsOf(p.id()).stream().filter(r -> !r.webResults().isEmpty()).toList();
                if (!web.isEmpty()) results.put(p.id(), web);
            });
            retrieved = new ChatRetrieval.Outcome(results, Map.of(), Set.of(), null, null, Set.of(), Map.of(), null, ran.faulted());
            coverage.read(confirmed, results);
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
            guard(control, limits.tools().plus(MIN_DIRECT_GENERATE).plus(MIN_VERIFY).plus(limits.server()));
            retrieved = retrieval.run(run, control, confirmed);
            if (retrieved.failed() != null) throw new Stop(toolFailure(retrieved.failed()));
            coverage.read(confirmed, retrieved.results());
            if (retrieved.stop() != null) return stopped(run, route, retrieved.stop(), coverage);
            if (retrieved.faulted() != null) {
                route.putArray("toolFaults").addAll(strings(retrieved.limitations().entrySet().stream()
                        .filter(e -> ChatRetrieval.TOOL_UNAVAILABLE.equals(e.getValue())).map(Map.Entry::getKey).toList()));
            }
            ChatPlan.Stop webScope = webScopeStop(run, confirmed, retrieved);
            if (webScope != null) return stopped(run, route, webScope, coverage);
            List<ChatModels.AgentRequirement> gaps = webGaps(run, confirmed, retrieved);
            if (!gaps.isEmpty()) {
                WebAfterReads web = webAfterReads(run, control, gaps, directStart, route);
                agentNotices = web.notices();
                if (!web.hits().isEmpty()) {
                    retrieved = retrieved.withResults(web.hits());
                    coverage.read(confirmed, retrieved.results());
                }
            }
        }

        Map<String, Planned> byId = new LinkedHashMap<>();
        confirmed.requirements().forEach(p -> byId.put(p.id(), p));
        Map<String, String> limited = new LinkedHashMap<>();
        confirmed.requirements().stream().filter(p -> p.mode() == Mode.LIMITED).forEach(p -> limited.put(p.id(), p.limitation()));
        limited.putAll(retrieved.limitations());
        limited.forEach(coverage::limited);
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
                        limited.containsValue("investment_advice") ? "investment_advice" : "out_of_scope", List.of()),
                        coverage);
            }
            return insufficient(run, route, limited.containsValue("results_truncated") ? RESULTS_TRUNCATED
                    : limited.containsValue("not_in_member_scope") ? NOT_IN_MEMBER_SCOPE
                    : limited.containsValue("precondition_unmet") ? PRECONDITION_UNMET : EVIDENCE_INSUFFICIENT,
                    confirmed, retrieved, coverage);
        }

        ChatGeneratedAnswer generated;
        if (agentAnswer != null) {
            generated = agentAnswer;
        } else {
            control.phase("writing");
            var context = new ChatBranchContext(run.turns(), run.context(), branches, ChatAnswerCheck.MAX_CITATIONS);
            generated = modelAtLeast(control, limits.generate(), MIN_DIRECT_GENERATE,
                    MIN_VERIFY.plus(limits.server()),
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
        ChatSemanticVerdicts verdicts = modelAtLeast(control, limits.verify(), MIN_VERIFY, limits.server(),
                () -> verifier.verify(run, passed.sections(), allCited, facts));
        Verified verified = verified(passed.sections(), verdicts);
        if (verified == null) return validationFailed();
        Set<String> held = verified.heldRequirements();
        route.putArray("heldRequirements").addAll(strings(held));
        route.putArray("droppedClaims").addAll(strings(verified.droppedClaims()));

        List<ChatGeneratedAnswer.Section> kept = verified.sections();
        Set<String> insufficient = new LinkedHashSet<>(passed.insufficient());
        passed.sections().stream().filter(s -> !kept.contains(s)).forEach(s -> insufficient.addAll(s.requirementIds()));
        // A requirement still answered by a kept section of its own is answered; a joining section goes with any held part.
        insufficient.removeIf(id -> kept.stream().anyMatch(s -> s.requirementIds().contains(id)));
        if (kept.isEmpty() && retrieved.faulted() != null) throw new Stop(toolFailure(retrieved.faulted()));
        if (kept.isEmpty() && !retrieved.partial().isEmpty()) throw new Stop(new ChatEngineOutcome.Failed("transient", null, true));
        if (kept.isEmpty()) {
            // The most specific cause the server knows: a limit it hit, then a verdict, then a lookup that found nothing.
            List<String> unanswered = insufficient.stream().filter(id -> byId.get(id).parent() == null).toList();
            InsufficientCause cause = limited.containsValue("results_truncated") ? RESULTS_TRUNCATED
                    : limited.containsValue("not_in_member_scope") ? NOT_IN_MEMBER_SCOPE
                    : unanswered.stream().anyMatch(held::contains) ? EVIDENCE_HELD
                    : !unanswered.isEmpty() && retrieved.noneFound().containsAll(unanswered) ? NOTHING_FOUND
                    : limited.containsValue("precondition_unmet") ? PRECONDITION_UNMET : EVIDENCE_INSUFFICIENT;
            return insufficient(run, route, cause, confirmed, retrieved, coverage);
        }

        Set<String> keptEvidence = new HashSet<>();
        kept.forEach(s -> keptEvidence.addAll(s.evidenceIds()));
        List<Citation> keptCitations = cited.values().stream().filter(c -> keptEvidence.contains(c.evidenceId())).toList();
        List<ChatLimitation> limitations = new ArrayList<>();
        for (var entry : limited.entrySet()) {
            Planned p = byId.get(entry.getKey());
            if (explicit(decision, p.id())) limitations.add(ChatResults.limitation(entry.getValue(), p.label()));
        }
        kept.forEach(s -> s.requirementIds().forEach(coverage::answered));
        for (String id : insufficient) {
            if (retrieved.partial().contains(id)) {
                // Unanswered with a read missing: the fault, never "no evidence".
                coverage.limited(id, ChatRetrieval.TOOL_UNAVAILABLE);
                if (explicit(decision, id)) {
                    limitations.add(ChatResults.limitation(ChatRetrieval.TOOL_UNAVAILABLE, byId.get(id).label()));
                }
                continue;
            }
            InsufficientCause cause = held.contains(id) ? EVIDENCE_HELD
                    : retrieved.noneFound().contains(id) ? NOTHING_FOUND : EVIDENCE_INSUFFICIENT;
            coverage.limited(id, cause.code());
            if (explicit(decision, id)) limitations.add(ChatResults.insufficient(cause, byId.get(id).label()));
        }
        if (!coverage.settled()) return validationFailed();
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
        Set<String> partialFaults = retrieved.partial();
        List<String> readInPart = confirmed.requirements().stream().map(Planned::id)
                .filter(id -> partialFaults.contains(id) && answered.contains(id)).toList();
        if (!partialFaults.isEmpty()) route.putArray("partialFaults").addAll(strings(partialFaults));
        // A map target stays only while a requirement whose tools returned it is still answered.
        Set<String> reachable = new HashSet<>();
        branches.stream().filter(b -> answered.contains(b.requirementId()))
                .forEach(b -> b.results().forEach(r -> r.items().forEach(i -> reachable.add(i.id()))));
        var targets = passed.graphTargets().stream().filter(g -> reachable.contains(g.id())).toList();
        ChatResult result = ChatResults.answered(run, kept, keptCitations, targets,
                items(retrieved, answered, "company"), items(retrieved, answered, "issue"), limitations, partial,
                notices(directStart, agentNotices, readInPart.stream().filter(id -> explicit(decision, id))
                        .map(id -> byId.get(id).label()).toList()), overrode(run, confirmed, answered),
                writtenPeriod(run, confirmed, answered),
                ChatUiActions.of(branches, answered, targets, ChatUiActions.citedArticles(kept, keptCitations),
                        run.graphVersionId(), run.context().asOf()), clock.instant());
        route.put("outcome", "answered").set("coverage", coverage.json());
        return new ChatEngineOutcome.Completed(result, route);
    }

    /**
     * Nothing could be answered: the reason says why and what to try, and {@code applied} shows what the reads looked at
     * (every requirement's, since none was answered).
     */
    private ChatEngineOutcome insufficient(ChatRun run, ObjectNode route, InsufficientCause cause, ChatPlan.Run plan,
            ChatRetrieval.Outcome retrieved, ChatRequirementCoverage coverage) {
        coverage.end(ChatRequirementCoverage.Status.LIMITED, cause.code());
        route.put("outcome", "insufficient_evidence").put("reason", cause.code()).set("coverage", coverage.json());
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

    private record Verified(List<ChatGeneratedAnswer.Section> sections, Set<String> heldRequirements,
            List<String> droppedClaims) { }

    /**
     * Keeps only claims that are supported (where support applies) and have no unsupported causal assertion. A held,
     * contradicted or causally unsupported claim is omitted without discarding its section's safe claims. A section with no
     * safe claim holds back all of its requirements. Definite prohibited advice still invalidates the whole generated answer.
     */
    private static Verified verified(List<ChatGeneratedAnswer.Section> sections, ChatSemanticVerdicts verdicts) {
        if (verdicts.sections().size() != sections.size()) throw malformedVerdicts();
        List<ChatGeneratedAnswer.Section> keptSections = new ArrayList<>();
        Set<String> held = new LinkedHashSet<>();
        List<String> dropped = new ArrayList<>();
        for (int i = 0; i < sections.size(); i++) {
            var section = sections.get(i);
            var verdict = verdicts.sections().get(i);
            boolean general = "general_knowledge".equals(section.basis());
            List<ChatClaims.Claim> claims = ChatClaims.split(i, section.text());
            boolean scriptedSectionVerdict = verdict.claims().size() == 1 && verdict.claims().getFirst().claimId() == null;
            if (!ADVICE.contains(verdict.prohibitedAdvice())
                    || (!scriptedSectionVerdict && verdict.claims().size() != claims.size())) {
                throw malformedVerdicts();
            }
            if ("yes".equals(verdict.prohibitedAdvice())) return null;
            List<ChatClaims.Claim> kept = new ArrayList<>();
            for (int claimIndex = 0; claimIndex < claims.size(); claimIndex++) {
                ChatClaims.Claim claim = claims.get(claimIndex);
                ChatSemanticVerdicts.ClaimVerdict decision = scriptedSectionVerdict
                        ? verdict.claims().getFirst() : verdict.claims().get(claimIndex);
                if ((!scriptedSectionVerdict && !claim.id().equals(decision.claimId()))
                        || !ADVICE.contains(decision.unsupportedCausality())
                        || (general ? decision.support() != null : !SUPPORT.contains(decision.support()))) {
                    throw malformedVerdicts();
                }
                boolean safe = "no".equals(verdict.prohibitedAdvice())
                        && (general || "supported".equals(decision.support()))
                        && "no".equals(decision.unsupportedCausality());
                if (safe) kept.add(claim);
                else dropped.add(claim.id());
            }
            if (kept.isEmpty()) {
                held.addAll(section.requirementIds());
            } else {
                keptSections.add(new ChatGeneratedAnswer.Section(section.basis(),
                        String.join(" ", kept.stream().map(ChatClaims.Claim::text).toList()), section.requirementIds(),
                        section.evidenceIds()));
            }
        }
        return new Verified(List.copyOf(keptSections), Collections.unmodifiableSet(new LinkedHashSet<>(held)),
                List.copyOf(dropped));
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
        return awaitModel(control, stage, call);
    }

    /**
     * A direct model stage with a fixed minimum and a larger provisional ceiling. It uses slack left by faster earlier stages
     * but never consumes the minimum reserved for the stages and terminal write after it.
     */
    private <T> T modelAtLeast(ChatRunControl control, Duration ceiling, Duration minimum, Duration after,
            Supplier<T> call) {
        guard(control, minimum.plus(after));
        Duration available = control.remaining().minus(after);
        return awaitModel(control, min(ceiling, available), call);
    }

    private <T> T awaitModel(ChatRunControl control, Duration stage, Supplier<T> call) {
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
     * read at all (a plan of general and limited requirements needs no tools). It also leaves to the direct path what a tool's
     * arguments cannot carry, so a question reads the same on both ({@link #agentReadsLikeDirect}).
     */
    List<ChatCapability> agentTools(ChatRun run, ChatPlan.Run plan) {
        if (agent == null) return null;
        Set<ChatCapability> exposed = agent.tools();
        Set<ChatCapability> tools = new LinkedHashSet<>();
        for (Planned p : plan.requirements()) {
            if (p.mode() != Mode.TOOLS) continue;
            if (p.origin() == ChatPlan.Origin.SCOPE || p.dependsOn() != null || p.stage() != 1
                    || p.targets().size() > ChatToolRequest.MAX_TARGETS || !exposed.containsAll(p.capabilities())
                    || !agentReadsLikeDirect(run, p)) {
                return null;
            }
            tools.addAll(p.capabilities());
        }
        // The web (web search design 1) is the first support of a concept (Q02: one search, tried by default) and the last
        // resort of a fact part (Q03~Q08: approved only once the internal reads serving it left something unmet). A
        // service-rule part (Q01) may not rest on it; the other parts of its question still may, each search bound to the
        // parts it names.
        if (plan.requirements().stream().anyMatch(OrchestratedChatEngine::webMayServe)
                && exposed.contains(ChatCapability.WEB_SEARCH)) {
            // A concept question with no read of its own goes to the agent for its search alone.
            tools.add(ChatCapability.WEB_SEARCH);
        }
        return tools.isEmpty() ? null : List.copyOf(tools);
    }

    /**
     * Whether an MCP call would read what the plan reads. Its arguments are targets and a limit, and the server fills in the
     * rest from the run, which knows neither the requirement's own words nor where its targets came from. So a period read from
     * the question (or any period of a document read) and a requirement that names its own targets while the member
     * narrowed the selection to chosen evidence stay on the direct path.
     */
    private static boolean agentReadsLikeDirect(ChatRun run, Planned p) {
        boolean dated = p.capabilities().contains(ChatCapability.DOCUMENT_SEARCH)
                ? ChatRetrieval.period(run, p).isPresent()
                : p.capabilities().contains(ChatCapability.GRAPH_VERSION_DIFF)
                        && ChatPeriods.parse(p.label(), run.askedAt()).isPresent();
        boolean scopeDiffers = !run.selection().evidenceIds().isEmpty() && p.evidenceScope() == null
                && p.capabilities().stream().anyMatch(c -> c.documents().isEmpty());
        return !dated && !scopeDiffers;
    }

    private ChatAgentPath.Steps steps(ChatRunControl control, Instant end, Duration after, Duration closingAt) {
        return new ChatAgentPath.Steps() {
            @Override
            public ChatModels.AgentStep run(Supplier<ChatModels.AgentStep> step) {
                // Each step waits at most what is left of the budget, and never less than the time an answer needs.
                Duration limit = min(AGENT_STEP, Duration.between(clock.instant(), end));
                if (limit.compareTo(MIN_AGENT_STEP) < 0) throw new DeadlineGuard();
                return model(control, limit, after, step);
            }

            @Override
            public boolean closing() {
                return Duration.between(clock.instant(), end).compareTo(closingAt) < 0;
            }
        };
    }

    private record WebAfterReads(Map<String, List<ChatToolResult>> hits, List<String> notices) { }

    /**
     * The web search of a run the server read itself (Q05 with a period, Q06, Q07, Q08 and the other plans the agent cannot
     * read): Luna is offered the search alone, for the requirements {@link #webGaps} found unmet, and the server's gate decides
     * it as on the agent path. Only the hits come back; the answer is written by the generator from the reads and the hits, so
     * Luna's own closing answer is dropped. A fault here is a notice and never fails a run that has its reads.
     */
    private WebAfterReads webAfterReads(ChatRun run, ChatRunControl control, List<ChatModels.AgentRequirement> gaps,
            boolean agentRefused, ObjectNode route) {
        Duration after = MIN_DIRECT_GENERATE.plus(MIN_VERIFY).plus(limits.server());
        Duration budget = min(WEB_AFTER_READS, control.remaining().minus(after));
        if (budget.compareTo(MIN_AGENT_STEP) < 0) {
            route.put("webAfterReads", "no_time");
            return new WebAfterReads(Map.of(), List.of(WEB_BUDGET_EXHAUSTED));
        }
        if (agentRefused || !agent.available()) {
            route.put("webAfterReads", "unavailable");
            return new WebAfterReads(Map.of(), List.of(WEB_UNAVAILABLE));
        }
        ChatAgentPath.Outcome ran;
        try {
            ran = agent.run(run, control, gaps, List.of(ChatCapability.WEB_SEARCH), ChatAnswerCheck.MAX_CITATIONS,
                    steps(control, clock.instant().plus(budget), after, MIN_AGENT_STEP));
        } catch (ChatModels.Failure | DeadlineGuard fault) {
            route.put("webAfterReads", "failed");
            return new WebAfterReads(Map.of(), List.of(WEB_UNAVAILABLE));
        }
        Map<String, List<ChatToolResult>> hits = new LinkedHashMap<>();
        for (var gap : gaps) {
            List<ChatToolResult> found = ran.resultsOf(gap.id()).stream().filter(r -> !r.webResults().isEmpty()).toList();
            if (!found.isEmpty()) hits.put(gap.id(), found);
        }
        route.put("webAfterReads", "searched").put("webSteps", ran.steps()).put("webApproved", ran.approved())
                .put("webDenied", ran.denied());
        return new WebAfterReads(hits, ran.notices());
    }

    /**
     * The requirements of a server-read run the web may still add to (web search design 2). Their own reads ended, none failed
     * and none was bound to evidence the member chose. A public fact (Q03, Q04, Q07) with nothing found or a cut read qualifies.
     * What only ZOOP's records can say (the comparison, the published round, the selection of Q05, Q06, Q08) is never replaced
     * by the web, so an empty read opens nothing there; only words asking for an outside source do, for background beside it.
     */
    private List<ChatModels.AgentRequirement> webGaps(ChatRun run, ChatPlan.Run plan, ChatRetrieval.Outcome retrieved) {
        if (agent == null || !agent.tools().contains(ChatCapability.WEB_SEARCH)) return List.of();
        List<ChatModels.AgentRequirement> gaps = new ArrayList<>();
        for (Planned p : plan.requirements()) {
            if (p.mode() != Mode.TOOLS || p.origin() == ChatPlan.Origin.SCOPE || !webMayServe(p) || p.evidenceScope() != null
                    || retrieved.limitations().containsKey(p.id()) || retrieved.partial().contains(p.id())) continue;
            List<ChatToolResult> reads = retrieved.results().getOrDefault(p.id(), List.of());
            boolean recordsOnly = p.types().stream().anyMatch(RECORD_TYPES::contains);
            boolean incomplete = retrieved.noneFound().contains(p.id())
                    || ChatWebDemand.coverage(p.label(), run.askedAt(), p.targets(), reads,
                            id -> demandCitation(run, id)).incomplete();
            if (ChatWebDemand.asksExternalSource(p.label()) || incomplete && !recordsOnly) {
                gaps.add(ChatModels.AgentRequirement.searchOnly(p.id(), p.label()));
            }
        }
        return gaps;
    }

    /**
     * Q07 may read five member companies internally, but one run may search only two of them. If more than two still need
     * public facts, ask the member which pair to search before any search or final generation; never pick a pair by order.
     */
    private ChatPlan.Stop webScopeStop(ChatRun run, ChatPlan.Run plan, ChatRetrieval.Outcome retrieved) {
        if (agent == null || !agent.tools().contains(ChatCapability.WEB_SEARCH)) return null;
        for (Planned p : plan.requirements()) {
            if (p.mode() != Mode.TOOLS || !p.types().contains(ChatQueryType.Q07) || !p.onScope()
                    || p.evidenceScope() != null || retrieved.limitations().containsKey(p.id())
                    || retrieved.partial().contains(p.id())) continue;
            ChatRetrieval.Found scope = ChatRetrieval.found(
                    retrieved.results().getOrDefault(p.dependsOn().requirementId(), List.of()));
            if (scope.companies().size() <= 2) continue;
            List<ChatToolResult> reads = retrieved.results().getOrDefault(p.id(), List.of());
            Map<String, String> missing = new LinkedHashMap<>();
            boolean external = ChatWebDemand.asksExternalSource(p.label());
            scope.companies().forEach((id, label) -> {
                if (external || ChatWebDemand.coverage(p.label(), run.askedAt(), List.of(id), reads,
                        evidenceId -> demandCitation(run, evidenceId)).incomplete()) {
                    missing.put(id, label);
                }
            });
            if (missing.size() > 2) {
                var pair = new ChatRouteDecision.Dependency("web", "exactly", 2);
                return ChatPlanner.clarify(run, "web_company_selection",
                        ChatRetrieval.choices(new ChatRetrieval.Found(missing, false), pair));
            }
        }
        return null;
    }

    /** A refused or temporarily unreadable internal citation never becomes permission to replace it with the web. */
    private Optional<Citation> demandCitation(ChatRun run, String evidenceId) {
        try {
            return citations.cite(evidenceId, run.graphVersionId(), run.context().asOf(), run.jobId());
        } catch (ChatToolUnavailable unavailable) {
            return Optional.empty();
        }
    }

    /** Whether the agent was offered nothing but the web: a concept question with no read of its own. */
    private static boolean webOnly(List<ChatCapability> tools) {
        return tools != null && tools.equals(List.of(ChatCapability.WEB_SEARCH));
    }

    /**
     * The public citation of a web hit (web search design 6): its server id, snippet, title, domain as publisher, provider
     * as {@code docId}, publication time and URL. It is no ZOOP evidence and never becomes one.
     */
    public static Citation webCitation(ChatWebResult hit) {
        return new Citation("web_result", hit.id(), hit.snippet(), null, null, hit.provider(), null, 0,
                hit.snippet().codePointCount(0, hit.snippet().length()), hit.title(), hit.domain(), hit.publishedAt(),
                hit.url());
    }

    /** What the answer went on without: a direct start, the web faults of an agent run, and reads of answered requirements. */
    private static List<ChatNotice> notices(boolean directStart, List<String> agentNotices, List<String> readInPart) {
        List<ChatNotice> notices = new ArrayList<>();
        if (directStart) notices.add(ChatResults.notice("mcp_direct_start"));
        agentNotices.forEach(code -> notices.add(ChatResults.notice(code)));
        if (!readInPart.isEmpty()) notices.add(ChatResults.notice(ChatRetrieval.TOOL_UNAVAILABLE, readInPart));
        return notices;
    }

    /** The question types whose unmet requirements may fall back on the web (web search design 1). */
    private static final Set<ChatQueryType> WEB_TYPES = Set.of(ChatQueryType.Q03, ChatQueryType.Q04, ChatQueryType.Q05,
            ChatQueryType.Q06, ChatQueryType.Q07, ChatQueryType.Q08);

    /** The question types whose answer is ZOOP's own record, which no web result stands in for (web search design 2). */
    private static final Set<ChatQueryType> RECORD_TYPES = Set.of(ChatQueryType.Q05, ChatQueryType.Q06, ChatQueryType.Q08);
    private static final String WEB_UNAVAILABLE = "web_unavailable";
    private static final String WEB_BUDGET_EXHAUSTED = "web_budget_exhausted";

    /** Whether a search may serve this requirement at all: a concept or a fact part, and no service rule. */
    private static boolean webMayServe(Planned p) {
        return !p.types().contains(ChatQueryType.Q01) && (p.mode() == Mode.GENERAL
                || p.mode() == Mode.TOOLS && p.types().stream().anyMatch(WEB_TYPES::contains));
    }

    /** The answerable requirements of the plan as the agent sees them: reads with their resolved targets, general parts. */
    private static List<ChatModels.AgentRequirement> agentRequirements(ChatPlan.Run plan) {
        return plan.requirements().stream().filter(p -> p.mode() == Mode.TOOLS || p.mode() == Mode.GENERAL)
                .map(p -> new ChatModels.AgentRequirement(p.id(), p.label(), p.mode() == Mode.GENERAL,
                        p.mode() == Mode.TOOLS ? p.targets() : List.of(), webMayServe(p),
                        ChatWebDemand.asksExternalSource(p.label())))
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

    private ChatEngineOutcome stopped(ChatRun run, ObjectNode route, ChatPlan.Stop stop, ChatRequirementCoverage coverage) {
        coverage.stopped(stop);
        route.put("outcome", stop.outcome()).put("reason", stop.reason()).set("coverage", coverage.json());
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
