package com.zoop.chat.orchestrator;

import java.util.List;
import java.util.Map;

/**
 * The router's typed decision (AI chatbot implementation plan, stage 3; {@code ChatRouteDecision}): the question split into
 * requirements, each with Noul probabilities per Q type and per logical capability. It is a model output, so the server
 * trusts none of it beyond its shape: thresholds, the allowlist, the registry and the budget decide what runs.
 *
 * <p>{@code ambiguity} is set when the question names a target or period the router could not fix; its options (possibly
 * none, for free input) become a clarification.
 */
public record ChatRouteDecision(List<Requirement> requirements, Ambiguity ambiguity) {
    public ChatRouteDecision {
        requirements = requirements == null ? List.of() : List.copyOf(requirements);
    }

    /**
     * One requirement. {@code explicit} marks what the member asked for in words: it is never dropped by probability.
     * {@code targets} are ids the question itself names (they take precedence over the selected context).
     * {@code prohibitedAdvice} is the Noul probability that the requirement asks for an investment decision.
     * {@code dependsOn} declares that the requirement runs on what another one finds.
     */
    public record Requirement(String id, String label, boolean explicit, Map<ChatQueryType, Double> types,
            Map<String, Double> capabilities, List<String> targets, double prohibitedAdvice, Dependency dependsOn) {
        public Requirement {
            types = types == null ? Map.of() : Map.copyOf(types);
            capabilities = capabilities == null ? Map.of() : Map.copyOf(capabilities);
            targets = targets == null ? List.of() : List.copyOf(targets);
        }
    }

    /**
     * The requirement's targets are the companies {@code requirementId} finds, and it runs only when their count meets the
     * checkpoint: {@code exactly}, {@code atLeast} or {@code atMost} {@code count} (design summary 5.2).
     */
    public record Dependency(String requirementId, String cardinality, int count) { }

    /** What the member must pick: {@code kind} is a {@code ChatChoice} kind; no options means free input. */
    public record Ambiguity(String kind, List<Option> options) {
        public Ambiguity {
            options = options == null ? List.of() : List.copyOf(options);
        }
    }

    public record Option(String id, String label) { }
}
