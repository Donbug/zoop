package com.zoop.chat.orchestrator;

import static com.zoop.chat.orchestrator.ChatResults.InsufficientCause.*;

import com.zoop.chat.dto.ChatAppliedItem;
import com.zoop.chat.dto.ChatAppliedPeriod;
import com.zoop.chat.dto.ChatLimitation;
import com.zoop.chat.dto.ChatResult;
import com.zoop.chat.dto.Citation;
import com.zoop.chat.executor.ChatEngine;
import com.zoop.chat.executor.ChatEngineOutcome;
import com.zoop.chat.executor.ChatRun;
import com.zoop.chat.executor.ChatRunControl;
import com.zoop.chat.orchestrator.ChatBranchContext.Branch;
import com.zoop.chat.orchestrator.ChatPlan.Mode;
import com.zoop.chat.orchestrator.ChatPlan.Planned;
import com.zoop.chat.orchestrator.ChatResults.InsufficientCause;
import com.zoop.chat.tool.ChatCapability;
import com.zoop.chat.tool.ChatToolRegistry;
import com.zoop.chat.tool.ChatToolResult;
import com.zoop.chat.tool.ChatToolRunner;
import com.zoop.chat.tool.ChatToolUnavailable;
import com.zoop.common.json.StrictJson;
import java.time.Clock;
import java.time.Duration;
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

    public OrchestratedChatEngine(ChatModels.Router router, ChatModels.Generator generator, ChatModels.Verifier verifier,
            ChatToolRegistry registry, ChatToolRunner runner, ChatCitationSource citations, Clock clock) {
        this(router, generator, verifier, registry, runner, citations, clock, StageLimits.POLICY);
    }

    OrchestratedChatEngine(ChatModels.Router router, ChatModels.Generator generator, ChatModels.Verifier verifier,
            ChatToolRegistry registry, ChatToolRunner runner, ChatCitationSource citations, Clock clock,
            StageLimits limits) {
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
        if (confirmed.requirements().stream().anyMatch(p -> p.mode() == Mode.TOOLS)) {
            control.phase("retrieving");
            guard(control, limits.tools().plus(limits.generate()).plus(limits.verify()).plus(limits.server()));
            retrieved = retrieval.run(run, control, confirmed);
            if (retrieved.failed() != null) throw new Stop(toolFailure(retrieved.failed()));
            if (retrieved.stop() != null) return stopped(run, route, retrieved.stop());
        }

        Map<String, Planned> byId = new LinkedHashMap<>();
        confirmed.requirements().forEach(p -> byId.put(p.id(), p));
        Map<String, String> limited = new LinkedHashMap<>();
        confirmed.requirements().stream().filter(p -> p.mode() == Mode.LIMITED).forEach(p -> limited.put(p.id(), p.limitation()));
        limited.putAll(retrieved.limitations());
        List<Branch> branches = new ArrayList<>();
        for (Planned p : confirmed.requirements()) {
            if (p.mode() == Mode.LIMITED || limited.containsKey(p.id())) continue;
            List<String> avoid = p.parent() == null ? List.of()
                    : labels(retrieved.results().getOrDefault(p.parent(), List.of()));
            branches.add(new Branch(p.id(), p.label(), p.types(), p.mode() == Mode.GENERAL,
                    retrieved.results().getOrDefault(p.id(), List.of()), retrieved.noneFound().contains(p.id()),
                    p.parent(), avoid));
        }
        route.set("limited", json(limited));
        if (branches.isEmpty()) {
            boolean unanswerable = limited.values().stream().allMatch(k -> k.equals("investment_advice") || k.equals("out_of_scope"));
            if (unanswerable) {
                return stopped(run, route, new ChatPlan.Stop("guidance",
                        limited.containsValue("investment_advice") ? "investment_advice" : "out_of_scope", List.of()));
            }
            return insufficient(run, route, limited.containsValue("results_truncated") ? RESULTS_TRUNCATED
                    : limited.containsValue("precondition_unmet") ? PRECONDITION_UNMET : EVIDENCE_INSUFFICIENT,
                    confirmed, retrieved);
        }

        control.phase("writing");
        var context = new ChatBranchContext(run.turns(), run.context(), branches, ChatAnswerCheck.MAX_CITATIONS);
        ChatGeneratedAnswer generated = model(control, limits.generate(), limits.verify().plus(limits.server()),
                () -> generator.generate(run, context));
        var checked = ChatAnswerCheck.check(branches, generated);
        route.put("deterministicCheck", checked.failedCheck() == null ? "passed" : checked.failedCheck());
        if (checked.failedCheck() != null) return validationFailed();
        var passed = checked.passed();
        if (!passed.dropped().isEmpty()) route.putArray("droppedGeneral").addAll(strings(passed.dropped()));

        Map<String, Citation> cited = new LinkedHashMap<>();
        for (var section : passed.sections()) {
            for (String id : section.evidenceIds()) {
                Citation citation = cited.get(id);
                if (citation == null) {
                    Optional<Citation> read = citations.cite(id, run.graphVersionId(), run.context().asOf(), run.jobId());
                    // Readable when the tool passed it on and not now: the answer cannot stand on it.
                    if (read.isEmpty()) return validationFailed();
                    citation = read.get();
                    cited.put(id, citation);
                }
                // A ZOOP document section quotes ZOOP documents only, and no other section quotes them.
                if ("zoop_documented".equals(section.basis()) != "zoop_doc".equals(citation.sourceKind())) {
                    return validationFailed();
                }
            }
        }

        control.phase("verifying");
        List<Citation> allCited = List.copyOf(cited.values());
        ChatSemanticVerdicts verdicts = model(control, limits.verify(), limits.server(),
                () -> verifier.verify(run, passed.sections(), allCited));
        Set<String> held = held(passed.sections(), verdicts);
        if (held == null) return validationFailed();
        route.putArray("heldRequirements").addAll(strings(held));

        List<ChatGeneratedAnswer.Section> kept = passed.sections().stream()
                .filter(s -> s.requirementIds().stream().noneMatch(held::contains)).toList();
        Set<String> insufficient = new LinkedHashSet<>(passed.insufficient());
        passed.sections().stream().filter(s -> !kept.contains(s)).forEach(s -> insufficient.addAll(s.requirementIds()));
        // A requirement still answered by a kept section of its own is answered; a joining section goes with any held part.
        insufficient.removeIf(id -> kept.stream().anyMatch(s -> s.requirementIds().contains(id)));
        if (kept.isEmpty()) {
            // The most specific cause the server knows: a limit it hit, then a verdict, then a lookup that found nothing.
            List<String> unanswered = insufficient.stream().filter(id -> byId.get(id).parent() == null).toList();
            InsufficientCause cause = limited.containsValue("results_truncated") ? RESULTS_TRUNCATED
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

        Set<String> answered = new HashSet<>();
        kept.forEach(s -> answered.addAll(s.requirementIds()));
        // A map target stays only while a requirement whose tools returned it is still answered.
        Set<String> reachable = new HashSet<>();
        branches.stream().filter(b -> answered.contains(b.requirementId()))
                .forEach(b -> b.results().forEach(r -> r.items().forEach(i -> reachable.add(i.id()))));
        var targets = passed.graphTargets().stream().filter(g -> reachable.contains(g.id())).toList();
        ChatResult result = ChatResults.answered(run, kept, keptCitations, targets,
                items(retrieved, answered, "company"), items(retrieved, answered, "issue"), limitations,
                overrode(run, confirmed, answered), writtenPeriod(run, confirmed, answered), clock.instant());
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

    /** The period an answered comparison read from the question's own words, or null when none did. */
    private static ChatAppliedPeriod writtenPeriod(ChatRun run, ChatPlan.Run plan, Set<String> answered) {
        for (Planned p : plan.requirements()) {
            if (!answered.contains(p.id()) || !p.capabilities().contains(ChatCapability.GRAPH_VERSION_DIFF)) continue;
            var period = ChatRetrieval.period(run, p).filter(found -> found.expression() != null);
            if (period.isPresent()) {
                return new ChatAppliedPeriod(period.get().start().toString(), period.get().end().toString(), "question",
                        period.get().expression());
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
