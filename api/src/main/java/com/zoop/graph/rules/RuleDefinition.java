package com.zoop.graph.rules;

import com.zoop.common.json.StrictJson;
import java.util.LinkedHashSet;
import java.util.List;
import java.util.Set;

/**
 * The typed condition of one application publication rule ({@code publication_rules.definition}, rules doc
 * {@code docs/development/issue-133-publication-rules.md} 2-3). Only the kinds in code exist; there is no expression language.
 * A definition that does not parse exactly is {@link InvalidRuleDefinitionException}, so an enabled rule the app cannot read
 * fails the import instead of being skipped (fail closed: skipping it could publish what it should hide).
 */
public sealed interface RuleDefinition permits RuleDefinition.SingleSource, RuleDefinition.AssertionStatus {
    /** The relations that link an issue to a company; {@code FOLLOWS} (issue to issue) is never a single-source target. */
    Set<String> COMPANY_RELATIONS = Set.of("INVOLVES", "STRUCTURALLY_RELATED_TO");

    /** The producer's issue {@code assertionStatus} values. */
    Set<String> ASSERTION_STATUSES = Set.of("occurred", "announced", "planned", "forecast", "cancelled", "unknown");

    /**
     * {@code single_source}: hide a relation of {@code relationTypes} backed by fewer than {@code minSources} distinct articles
     * (rules doc, rule 1). {@code minSources} is 2 to 100: 1 would hide nothing, and above 100 is no realistic source count.
     */
    record SingleSource(int minSources, Set<String> relationTypes) implements RuleDefinition {
        public SingleSource {
            if (minSources < 2 || minSources > 100) throw new InvalidRuleDefinitionException("single_source.minSources");
            if (relationTypes.isEmpty() || !COMPANY_RELATIONS.containsAll(relationTypes)) {
                throw new InvalidRuleDefinitionException("single_source.relationTypes");
            }
            relationTypes = Set.copyOf(relationTypes);
        }
    }

    /** {@code assertion_status}: hide an issue whose {@code assertionStatus} is in {@code hide} (rules doc, rule 2). */
    record AssertionStatus(Set<String> hide) implements RuleDefinition {
        public AssertionStatus {
            if (hide.isEmpty() || !ASSERTION_STATUSES.containsAll(hide)) {
                throw new InvalidRuleDefinitionException("assertion_status.hide");
            }
            hide = Set.copyOf(hide);
        }
    }

    /** Parses a stored definition: an exact object for one known {@code kind}, with no unknown or repeated values. */
    static RuleDefinition parse(String json) {
        try {
            StrictJson.Obj definition = StrictJson.parseObject(json);
            String kind = definition.string("kind");
            return switch (kind) {
                case "single_source" -> {
                    definition.exactly(Set.of("kind", "minSources", "relationTypes"));
                    yield new SingleSource(definition.count("minSources"), distinct(definition.strings("relationTypes")));
                }
                case "assertion_status" -> {
                    definition.exactly(Set.of("kind", "hide"));
                    yield new AssertionStatus(distinct(definition.strings("hide")));
                }
                default -> throw new InvalidRuleDefinitionException("kind");
            };
        } catch (StrictJson.Malformed malformed) {
            throw new InvalidRuleDefinitionException("malformed");
        }
    }

    private static Set<String> distinct(List<String> values) {
        Set<String> set = new LinkedHashSet<>(values);
        if (set.size() != values.size()) throw new InvalidRuleDefinitionException("repeated value");
        return set;
    }
}
