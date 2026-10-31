package com.zoop.chat.orchestrator;

import com.zoop.chat.dto.ChatAppliedItem;
import com.zoop.chat.dto.ChatChoice;
import com.zoop.chat.executor.ChatRun;
import com.zoop.chat.executor.ChatRunControl;
import com.zoop.chat.orchestrator.ChatPlan.Mode;
import com.zoop.chat.orchestrator.ChatPlan.Planned;
import com.zoop.chat.orchestrator.ChatPlan.TargetSource;
import com.zoop.chat.tool.ChatCapability;
import com.zoop.chat.tool.ChatToolRequest;
import java.util.ArrayList;
import java.util.Collection;
import java.util.Comparator;
import java.util.EnumSet;
import java.util.HashMap;
import java.util.HashSet;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.Optional;
import java.util.Set;
import java.util.regex.Pattern;

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
 * <li>Targets named in the question take precedence over the selected context, and that over what the last answers applied
 * ({@link ChatRun.Prior}): one candidate is used, several are asked; a lookup with none of them is ambiguous. When
 * the context is used and the member narrowed it to chosen evidence, the requirement (and what depends on it) may read and
 * cite only that evidence. A ZOOP document capability (Q01) always reads its fixed documents, so a requirement that reads
 * only those needs no target and no frozen graph.</li>
 * <li>General knowledge answers a pure Q02 requirement only. A requirement that also asks for a current fact needs a lookup
 * or is {@code out_of_scope}; it never falls back to a general answer. Its Q02 part is split off as a concept requirement
 * of the server's own ({@link ChatPlan.Origin#CONCEPT}, id {@code <id>-c}), answered from general knowledge whatever the
 * fact part finds (partial-answer design, part 1).</li>
 * <li>Before any call: more than 6 explicit requirements, an ambiguity, more than 3 dependent stages or more than 12 calls in
 * the worst case the checkpoints allow end as {@code clarification}. At clarification depth 2 every such stop is
 * {@code guidance} instead (ZOOP-AIG-001 6.3.4).</li>
 * </ul>
 */
public class ChatPlanner {
    static final double TAKE = 0.70;
    public static final double REVIEW = 0.35;
    static final double ADVICE = 0.10;
    static final int MAX_REQUIREMENTS = 6;
    static final int MAX_STAGES = 3;
    static final int MAX_CHOICES = 6;
    /** Branches the answer stage takes at most, and the longest requirement id it accepts (zoop-ai-chat-4). */
    static final int MAX_BRANCHES = 6;
    static final int MAX_ID = 32;
    /** Words pointing back at a company or an event; the lookbehind keeps a particle out ("삼성이 기업을"). */
    private static final Pattern COMPANY = Pattern.compile("(?<![가-힣])(?:그|이|저|해당)\\s*(?:회사|기업|종목|곳)|(?<![가-힣])거기");
    private static final Pattern EVENT = Pattern.compile("(?<![가-힣])(?:그|이|저|해당)\\s*(?:사건|이슈)");
    private static final Pattern POINTER = Pattern.compile(COMPANY.pattern() + "|" + EVENT.pattern()
            + "|(?<![가-힣])(?:그것|그거|이거|저거)");

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
        for (var stated : kept) {
            // "That company" with one candidate from the last answers reads as if the question named it; several are asked.
            var candidates = referred(run, stated);
            if (candidates.size() > 1) return clarifyCandidates(run, candidates);
            var requirement = candidates.isEmpty() ? stated : targeted(stated, candidates);
            Planned p = serve(run, requirement, bound, planned);
            if (p == null) {
                var carried = carried(run, stated.label());
                return carried.size() > 1 ? clarifyCandidates(run, carried) : clarify(run, "ambiguous_target", List.of());
            }
            if (p.onScope()) {
                Planned scope = p.scope(named(requirement, p));
                planned.put(scope.id(), scope);
            }
            planned.put(p.id(), p);
        }
        if (planned.values().stream().anyMatch(p -> p.mode() == Mode.TOOLS
                && p.capabilities().stream().anyMatch(ChatCapability::readsGraph)) && run.graphVersionId() == null) {
            return new ChatPlan.Stop("guidance", "graph_unavailable", List.of());
        }
        List<Planned> requirements = withConcepts(decision, planned.values());
        if (requirements.stream().allMatch(p -> p.mode() == Mode.LIMITED)) {
            boolean advice = planned.values().stream().anyMatch(p -> "investment_advice".equals(p.limitation()));
            return new ChatPlan.Stop("guidance", advice ? "investment_advice" : "out_of_scope", List.of());
        }
        var plan = new ChatPlan.Run(requirements);
        if (plan.stages() > MAX_STAGES || worstCaseCalls(plan) > ChatRunControl.MAX_TOOL_CALLS) {
            return clarify(run, "plan_over_budget", List.of());
        }
        return plan;
    }

    /**
     * The plan with the Q02 part of each router requirement that also asks for something else split off right after it as a
     * general requirement of its own, so the concept is answered even when the rest finds no evidence or cannot be looked
     * up. Not for an investment decision, and only while the answer stage has room for one more branch.
     */
    private static List<Planned> withConcepts(ChatRouteDecision decision, Collection<Planned> planned) {
        Set<String> ids = new HashSet<>();
        decision.requirements().forEach(r -> ids.add(r.id()));
        long room = MAX_BRANCHES - planned.stream()
                .filter(p -> p.mode() != Mode.LIMITED && p.origin() != ChatPlan.Origin.SCOPE).count();
        List<Planned> requirements = new ArrayList<>();
        for (Planned p : planned) {
            requirements.add(p);
            String id = p.id() + Planned.CONCEPT_ID;
            if (room > 0 && p.mode() != Mode.GENERAL && p.types().contains(ChatQueryType.Q02)
                    && !"investment_advice".equals(p.limitation()) && id.length() <= MAX_ID && ids.add(id)) {
                requirements.add(p.concept());
                room--;
            }
        }
        return List.copyOf(requirements);
    }

    /**
     * Calls the plan can make at most: every capability per batch of its targets ({@link ChatRetrieval#batches}), a dependent
     * stage at its checkpoint's most.
     */
    static int worstCaseCalls(ChatPlan.Run plan) {
        int calls = 0;
        for (Planned p : plan.requirements()) {
            if (p.mode() != Mode.TOOLS) continue;
            int targets = p.dependsOn() == null ? p.targets().size()
                    : ("atLeast".equals(p.dependsOn().cardinality()) ? ChatToolRequest.MAX_TARGETS : p.dependsOn().count())
                            + (p.onScope() ? p.targets().size() : 0);
            for (ChatCapability capability : p.capabilities()) {
                calls += chunks(capability, capability.documents().isEmpty() ? targets : capability.documents().size());
            }
        }
        return calls;
    }

    static int chunks(ChatCapability capability, int targets) {
        if (capability == ChatCapability.GRAPH_PATH_READ) {
            // Every call carries the first target and at most four of the others.
            int per = ChatToolRequest.MAX_TARGETS - 1;
            return Math.max(1, (targets - 1 + per - 1) / per);
        }
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
        // A question that names a company or an issue asks about it, not only a concept, once Q03 reaches the review band.
        if (all.equals(Set.of(ChatQueryType.Q02)) && !r.targets().isEmpty()
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
        // Server defaults for companies and issues the question names (never for a dependent stage), whatever the capability
        // probabilities: a company fact reads the company, an issue fact reads the issue, and a relation between two or
        // more companies reads the path. Each still has to be allowed by the type and bound.
        Set<ChatCapability> defaults = EnumSet.noneOf(ChatCapability.class);
        long companies = r.dependsOn() == null ? r.targets().stream().filter(ChatPlanner::companyId).count() : 0;
        long issues = r.dependsOn() == null ? r.targets().size() - companies : 0;
        if (companies > 0 && all.contains(ChatQueryType.Q03)) defaults.add(ChatCapability.COMPANY_READ);
        if (issues > 0 && all.contains(ChatQueryType.Q03)) defaults.add(ChatCapability.ISSUE_READ);
        // An issue a briefing question names reads that issue's evidence: a round's own read shares its limit with the others.
        if (issues > 0 && all.contains(ChatQueryType.Q06)) defaults.add(ChatCapability.BRIEFING_EVIDENCE);
        // A period comparison compares the public graph, with or without a named target.
        if (r.dependsOn() == null && all.contains(ChatQueryType.Q05)) defaults.add(ChatCapability.GRAPH_VERSION_DIFF);
        // "My stocks" reads the member's own companies first, and a company fact reads them. A company the question names is
        // what "my stocks" is about ("my Samsung"), read only when it is the member's, unless the question asks for a
        // relation: then it is the point the member's companies are related to ("mine linked to Samsung") and is read too.
        boolean mine = r.dependsOn() == null && all.contains(ChatQueryType.Q07);
        boolean anchored = mine && companies > 0 && all.contains(ChatQueryType.Q04);
        if (mine) defaults.add(ChatCapability.PORTFOLIO_SCOPE_READ);
        if (mine && all.contains(ChatQueryType.Q03)) defaults.add(ChatCapability.COMPANY_READ);
        if ((companies >= 2 || anchored) && all.contains(ChatQueryType.Q04)) defaults.add(ChatCapability.GRAPH_PATH_READ);
        for (ChatCapability c : defaults) {
            if (permitted.contains(c) && bound.contains(c.id()) && !capabilities.contains(c)) capabilities.add(c);
        }
        // Only a requirement of its own reads the member's scope: a dependent stage reads on what its source found.
        if (!mine) capabilities.remove(ChatCapability.PORTFOLIO_SCOPE_READ);
        capabilities.sort(Comparator.comparing(ChatCapability::id));
        // A fact requirement without a lookup it may make is out of scope, even when it also asks about a concept.
        if (capabilities.isEmpty()) return base.limited("out_of_scope");

        // Q07: the member's companies come from their own scope, read by the server for the authenticated member. The rest
        // of the requirement reads on them in the next stage (at least one, at most the fan-out the scope read passes on).
        // A reference point and a named issue stay the requirement's own targets, read with the member's companies.
        if (mine && capabilities.contains(ChatCapability.PORTFOLIO_SCOPE_READ)) {
            List<String> named = anchored ? List.of() : r.targets().stream().filter(ChatPlanner::companyId).toList();
            List<ChatCapability> rest = capabilities.stream().filter(c -> c != ChatCapability.PORTFOLIO_SCOPE_READ).toList();
            if (rest.isEmpty()) {
                return new Planned(r.id(), r.label(), all, Mode.TOOLS, null, capabilities,
                        named.isEmpty() ? ChatCapability.PORTFOLIO_SCOPE_READ.untargeted() : named,
                        named.isEmpty() ? TargetSource.SERVER : TargetSource.QUESTION, null, null, 1);
            }
            var scope = new ChatRouteDecision.Dependency(r.id() + Planned.SCOPE_ID, "atLeast", 1);
            List<String> own = r.targets().stream().filter(t -> !named.contains(t)).toList();
            return new Planned(r.id(), r.label(), all, Mode.TOOLS, null, rest, own, TargetSource.DEPENDENCY, null,
                    scope, 2);
        }

        // ZOOP documents are read whatever the question names, so a requirement that reads only them needs no target.
        if (r.dependsOn() == null && capabilities.stream().noneMatch(c -> c.documents().isEmpty())) {
            return new Planned(r.id(), r.label(), all, Mode.TOOLS, null, capabilities, List.of(), TargetSource.SERVER, null,
                    null, 1);
        }
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
        if (targets.isEmpty()) {
            // Reads that can cover the whole public graph ("what changed on the map") need no target.
            if (capabilities.stream().allMatch(c -> !c.untargeted().isEmpty())) {
                return new Planned(r.id(), r.label(), all, Mode.TOOLS, null, capabilities,
                        capabilities.getFirst().untargeted(), TargetSource.SERVER, null, null, 1);
            }
            var carried = carried(run, r.label());
            if (carried.size() != 1) return null;
            return new Planned(r.id(), r.label(), all, Mode.TOOLS, null, capabilities, List.of(carried.getFirst().id()),
                    TargetSource.QUESTION, null, null, 1);
        }
        List<String> scope = selection.evidenceIds().isEmpty() ? null : selection.evidencePool();
        return new Planned(r.id(), r.label(), all, Mode.TOOLS, null, capabilities, targets, TargetSource.CONTEXT, scope,
                null, 1);
    }

    /**
     * The companies a Q07 requirement's scope source checks: those the question names that the planned requirement no longer
     * reads itself (none when it reads the member's companies on a reference point, or names no company).
     */
    private static List<String> named(ChatRouteDecision.Requirement r, Planned p) {
        return r.targets().stream().filter(t -> companyId(t) && !p.targets().contains(t)).toList();
    }

    /** The last answers' candidates of a requirement that points at something and names nothing; empty when it needs none. */
    private static List<ChatAppliedItem> referred(ChatRun run, ChatRouteDecision.Requirement r) {
        boolean selected = !run.selection().contextIds().isEmpty() || !run.selection().evidenceIds().isEmpty();
        // ZOOP's own documents (Q01) read no target: "this company" there is ZOOP.
        boolean reads = r.types().entrySet().stream().anyMatch(t -> t.getKey() != ChatQueryType.Q01 && t.getValue() >= REVIEW);
        if (selected || !reads || !r.targets().isEmpty() || r.dependsOn() != null || !POINTER.matcher(r.label()).find()) {
            return List.of();
        }
        return carried(run, r.label());
    }

    /**
     * What the last answers offer a requirement: their issues when it asks about an event, else their companies, else their
     * issues; only companies when it asks about a company. A choice the member made among them leaves that one.
     */
    private static List<ChatAppliedItem> carried(ChatRun run, String label) {
        var prior = run.prior();
        List<ChatAppliedItem> items = EVENT.matcher(label).find() && !prior.issues().isEmpty() ? prior.issues()
                : !prior.companies().isEmpty() || COMPANY.matcher(label).find() ? prior.companies() : prior.issues();
        Set<String> picked = new HashSet<>();
        run.turns().forEach(t -> picked.add(t.choiceId()));
        var chosen = items.stream().filter(i -> picked.contains(i.id())).toList();
        return chosen.isEmpty() ? items : chosen;
    }

    private static ChatPlan.Stop clarifyCandidates(ChatRun run, List<ChatAppliedItem> candidates) {
        List<ChatChoice> choices = candidates.size() > MAX_CHOICES ? List.of() : candidates.stream()
                .map(c -> new ChatChoice(c.id(), c.label(), companyId(c.id()) ? "company" : "other")).toList();
        return clarify(run, "ambiguous", choices);
    }

    private static ChatRouteDecision.Requirement targeted(ChatRouteDecision.Requirement r, List<ChatAppliedItem> items) {
        return new ChatRouteDecision.Requirement(r.id(), r.label(), r.explicit(), r.types(), r.capabilities(),
                items.stream().map(ChatAppliedItem::id).toList(), r.prohibitedAdvice(), r.dependsOn());
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
