package com.zoop.chat.orchestrator;

import com.zoop.chat.dto.ChatChoice;
import com.zoop.chat.executor.ChatRun;
import com.zoop.chat.executor.ChatRunControl;
import com.zoop.chat.orchestrator.ChatPlan.Mode;
import com.zoop.chat.orchestrator.ChatPlan.Planned;
import com.zoop.chat.orchestrator.ChatPlan.TargetSource;
import com.zoop.chat.tool.ChatCapability;
import com.zoop.chat.tool.ChatToolRequest;
import java.util.ArrayList;
import java.util.Comparator;
import java.util.EnumSet;
import java.util.HashMap;
import java.util.HashSet;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.Optional;
import java.util.Set;

/**
 * Turns the router's decision into the minimum sufficient plan the server allows (AI chatbot implementation plan, stage 2;
 * design summary 5 and 5.1). It never calls a tool: a plan that cannot run within the rules stops before the first call.
 *
 * <ul>
 * <li>Thresholds: a Q type or capability at {@code p >= 0.70} is taken. An explicit requirement with none takes its best
 * candidate at {@code p >= 0.35}; below that nothing is taken. A requirement the member did not state is kept only with a
 * type at 0.70.</li>
 * <li>Gates, whatever the model said: an investment decision ({@code prohibitedAdvice > 0.10}, so an uncertain one too) is a
 * {@code investment_advice} limitation; a requirement with no allowed and registered capability is {@code out_of_scope};
 * a requirement whose source cannot run is {@code precondition_unmet}. A capability is allowed only through its Q type
 * ({@link ChatQueryType}) and runs only when bound in the registry.</li>
 * <li>Targets named in the question take precedence over the selected context; a lookup with neither is ambiguous. When
 * the context is used and the member narrowed it to chosen evidence, the requirement (and what depends on it) may read and
 * cite only that evidence.</li>
 * <li>General knowledge answers a pure Q02 requirement only. A requirement that also asks for a current fact needs a lookup
 * or is {@code out_of_scope}; it never falls back to a general answer.</li>
 * <li>Before any call: more than 6 explicit requirements, an ambiguity, more than 3 dependent stages or more than 12 calls in
 * the worst case the checkpoints allow end as {@code clarification}. At clarification depth 2 every such stop is
 * {@code guidance} instead (ZOOP-AIG-001 6.3.4).</li>
 * </ul>
 */
public class ChatPlanner {
    static final double TAKE = 0.70;
    static final double REVIEW = 0.35;
    static final double ADVICE = 0.10;
    static final int MAX_REQUIREMENTS = 6;
    static final int MAX_STAGES = 3;
    static final int MAX_CHOICES = 6;

    public ChatPlan plan(ChatRun run, ChatRouteDecision decision, Set<String> bound) {
        validate(decision);
        List<ChatRouteDecision.Requirement> kept = decision.requirements().stream()
                .filter(r -> r.explicit() || r.types().values().stream().anyMatch(p -> p >= TAKE)).toList();
        if (kept.stream().filter(ChatRouteDecision.Requirement::explicit).count() > MAX_REQUIREMENTS) {
            return clarify(run, "too_many_requirements", List.of());
        }
        if (decision.ambiguity() != null) {
            var options = decision.ambiguity().options();
            List<ChatChoice> choices = options.size() > MAX_CHOICES ? List.of() : options.stream()
                    .map(o -> new ChatChoice(o.id(), o.label(), decision.ambiguity().kind())).toList();
            return clarify(run, "ambiguous", choices);
        }
        if (kept.isEmpty()) return new ChatPlan.Stop("guidance", "out_of_scope", List.of());

        Map<String, Planned> planned = new LinkedHashMap<>();
        for (var requirement : kept) {
            Planned p = serve(run, requirement, bound, planned);
            if (p == null) return clarify(run, "ambiguous_target", List.of());
            planned.put(p.id(), p);
        }
        if (planned.values().stream().anyMatch(p -> p.mode() == Mode.TOOLS) && run.graphVersionId() == null) {
            return new ChatPlan.Stop("guidance", "graph_unavailable", List.of());
        }
        if (planned.values().stream().allMatch(p -> p.mode() == Mode.LIMITED)) {
            boolean advice = planned.values().stream().anyMatch(p -> "investment_advice".equals(p.limitation()));
            return new ChatPlan.Stop("guidance", advice ? "investment_advice" : "out_of_scope", List.of());
        }
        var plan = new ChatPlan.Run(List.copyOf(planned.values()));
        if (plan.stages() > MAX_STAGES || worstCaseCalls(plan) > ChatRunControl.MAX_TOOL_CALLS) {
            return clarify(run, "plan_over_budget", List.of());
        }
        return plan;
    }

    /** Calls the plan can make at most: every capability per chunk of five targets, a dependent stage at its checkpoint's most. */
    static int worstCaseCalls(ChatPlan.Run plan) {
        int calls = 0;
        for (Planned p : plan.requirements()) {
            if (p.mode() != Mode.TOOLS) continue;
            int targets = p.dependsOn() == null ? p.targets().size()
                    : "atLeast".equals(p.dependsOn().cardinality()) ? ChatToolRequest.MAX_TARGETS : p.dependsOn().count();
            calls += p.capabilities().size() * chunks(targets);
        }
        return calls;
    }

    static int chunks(int targets) {
        return Math.max(1, (targets + ChatToolRequest.MAX_TARGETS - 1) / ChatToolRequest.MAX_TARGETS);
    }

    /** A stop that asks the member, or, at the end of the clarification chain, tells them how to ask instead. */
    static ChatPlan.Stop clarify(ChatRun run, String reason, List<ChatChoice> choices) {
        return run.clarificationDepth() >= 2 ? new ChatPlan.Stop("guidance", "clarification_limit", List.of())
                : new ChatPlan.Stop("clarification", reason, choices);
    }

    /** How one requirement is served; null when it needs a lookup target nobody named. */
    private Planned serve(ChatRun run, ChatRouteDecision.Requirement r, Set<String> bound, Map<String, Planned> earlier) {
        Set<ChatQueryType> types = take(r.types(), r.explicit()).map(Set::of).orElse(Set.of());
        Set<ChatQueryType> all = EnumSet.noneOf(ChatQueryType.class);
        r.types().forEach((type, p) -> {
            if (p >= TAKE) all.add(type);
        });
        if (all.isEmpty()) all.addAll(types);
        // A source the planner dropped (an unstated requirement below the threshold) cannot run either.
        Planned source = r.dependsOn() == null ? null : earlier.get(r.dependsOn().requirementId());
        int stage = source == null ? 1 : source.stage() + 1;
        var base = new Planned(r.id(), r.label(), all, Mode.LIMITED, null, List.of(), List.of(), null, null, r.dependsOn(),
                stage);

        if (r.prohibitedAdvice() > ADVICE) return base.limited("investment_advice");
        if (all.isEmpty()) return base.limited("out_of_scope");
        // A question that names a company asks about that company, not only a concept, once Q03 reaches the review band.
        if (all.equals(Set.of(ChatQueryType.Q02)) && r.targets().stream().anyMatch(ChatPlanner::companyId)
                && r.types().getOrDefault(ChatQueryType.Q03, 0.0) >= REVIEW) {
            all.add(ChatQueryType.Q03);
        }
        // Only a pure concept question is answered from general knowledge; Q02 never stands in for a current fact.
        if (all.equals(Set.of(ChatQueryType.Q02))) {
            return new Planned(r.id(), r.label(), all, Mode.GENERAL, null, List.of(), List.of(), null, null, null, 1);
        }

        Map<String, Double> allowed = new HashMap<>();
        Set<ChatCapability> permitted = EnumSet.noneOf(ChatCapability.class);
        all.forEach(type -> permitted.addAll(type.capabilities()));
        r.capabilities().forEach((id, p) -> ChatCapability.of(id)
                .filter(c -> permitted.contains(c) && bound.contains(c.id())).ifPresent(c -> allowed.put(c.id(), p)));
        List<ChatCapability> capabilities = new ArrayList<>(allowed.entrySet().stream().filter(e -> e.getValue() >= TAKE)
                .sorted(Map.Entry.comparingByKey()).map(e -> ChatCapability.of(e.getKey()).orElseThrow()).toList());
        if (capabilities.isEmpty()) {
            best(allowed).filter(e -> e.getValue() >= REVIEW)
                    .ifPresent(e -> capabilities.add(ChatCapability.of(e.getKey()).orElseThrow()));
        }
        // Server defaults for companies the question names (never for a dependent stage), whatever the capability
        // probabilities: a company fact reads the company, and a relation between two or more of them reads the path.
        // Each still has to be allowed by the type and bound.
        Set<ChatCapability> defaults = EnumSet.noneOf(ChatCapability.class);
        long companies = r.dependsOn() == null ? r.targets().stream().filter(ChatPlanner::companyId).count() : 0;
        if (companies > 0 && all.contains(ChatQueryType.Q03)) defaults.add(ChatCapability.COMPANY_READ);
        if (companies >= 2 && all.contains(ChatQueryType.Q04)) defaults.add(ChatCapability.GRAPH_PATH_READ);
        for (ChatCapability c : defaults) {
            if (permitted.contains(c) && bound.contains(c.id()) && !capabilities.contains(c)) capabilities.add(c);
        }
        capabilities.sort(Comparator.comparing(ChatCapability::id));
        // A fact requirement without a lookup it may make is out of scope, even when it also asks about a concept.
        if (capabilities.isEmpty()) return base.limited("out_of_scope");

        if (r.dependsOn() != null) {
            if (source == null || source.mode() != Mode.TOOLS) return base.limited("precondition_unmet");
            return new Planned(r.id(), r.label(), all, Mode.TOOLS, null, capabilities, List.of(), TargetSource.DEPENDENCY,
                    source.evidenceScope(), r.dependsOn(), stage);
        }
        if (!r.targets().isEmpty()) {
            return new Planned(r.id(), r.label(), all, Mode.TOOLS, null, capabilities, r.targets(), TargetSource.QUESTION,
                    null, null, 1);
        }
        // The selected context: its targets, or the selected evidence alone, narrowed to the evidence the member chose.
        var selection = run.selection();
        List<String> targets = !selection.contextIds().isEmpty() ? selection.contextIds() : selection.evidenceIds();
        if (targets.isEmpty()) return null;
        List<String> scope = selection.evidenceIds().isEmpty() ? null : selection.evidencePool();
        return new Planned(r.id(), r.label(), all, Mode.TOOLS, null, capabilities, targets, TargetSource.CONTEXT, scope,
                null, 1);
    }

    /** A catalog company id ({@code KRX:005930}, {@code ORG:OPENAI}); issue and evidence ids have no exchange prefix. */
    static boolean companyId(String id) {
        return id.indexOf(':') > 0;
    }

    /** The best type when only an explicit requirement may use the review band. */
    private static Optional<ChatQueryType> take(Map<ChatQueryType, Double> types, boolean explicit) {
        return best(types).filter(e -> e.getValue() >= TAKE || (explicit && e.getValue() >= REVIEW)).map(Map.Entry::getKey);
    }

    /** The highest probability; a tie goes to the smallest key, so the choice never depends on map order. */
    private static <K extends Comparable<K>> Optional<Map.Entry<K, Double>> best(Map<K, Double> candidates) {
        Comparator<Map.Entry<K, Double>> order = Map.Entry.comparingByValue();
        order = order.thenComparing(Map.Entry.comparingByKey(Comparator.reverseOrder()));
        return candidates.entrySet().stream().max(order);
    }

    /**
     * The decision's shape: distinct ids, dependencies on earlier requirements only (so no cycle), a known cardinality with
     * a count a dependent stage can take. A malformed decision is a provider error the run may repeat.
     */
    private static void validate(ChatRouteDecision decision) {
        Set<String> seen = new HashSet<>();
        for (var r : decision.requirements()) {
            if (r.id() == null || r.id().isBlank() || r.label() == null || r.label().isBlank() || !seen.add(r.id())) {
                throw malformed("requirement ids must be distinct and labelled");
            }
            if (r.types().values().stream().anyMatch(p -> p == null || p < 0 || p > 1)
                    || r.capabilities().values().stream().anyMatch(p -> p == null || p < 0 || p > 1)
                    || r.prohibitedAdvice() < 0 || r.prohibitedAdvice() > 1) {
                throw malformed("probabilities must be within [0, 1]");
            }
            var d = r.dependsOn();
            if (d != null && (!seen.contains(d.requirementId()) || d.requirementId().equals(r.id())
                    || !Set.of("exactly", "atLeast", "atMost").contains(d.cardinality())
                    || d.count() < 1 || d.count() > ChatToolRequest.MAX_TARGETS)) {
                throw malformed("a dependency must name an earlier requirement and a checkpoint of 1 to 5");
            }
        }
        if (decision.requirements().isEmpty() && decision.ambiguity() == null) throw malformed("no requirement");
    }

    private static ChatModels.Failure malformed(String why) {
        return new ChatModels.Failure(ChatModels.Failure.Fate.NOT_SENT, "malformed route decision: " + why);
    }
}
