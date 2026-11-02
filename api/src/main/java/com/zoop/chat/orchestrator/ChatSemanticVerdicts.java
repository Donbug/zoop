package com.zoop.chat.orchestrator;

import java.util.List;

/**
 * The semantic verifier's verdict per claim, grouped in section order ({@code ChatSemanticVerification}, after the S1
 * thresholds). {@code support} is {@code supported}, {@code contradicted} or {@code hold} for a grounded claim and null for a
 * {@code general_knowledge} claim. {@code unsupportedCausality} is {@code no}, {@code yes} or {@code hold} for every claim;
 * {@code prohibitedAdvice} uses the same values for the whole section.
 */
public record ChatSemanticVerdicts(List<Verdict> sections) {
    public ChatSemanticVerdicts {
        sections = sections == null ? List.of() : List.copyOf(sections);
    }

    public record ClaimVerdict(String claimId, String support, String unsupportedCausality) { }

    public record Verdict(String prohibitedAdvice, List<ClaimVerdict> claims) {
        public Verdict {
            claims = claims == null ? List.of() : List.copyOf(claims);
        }

        /** Compatibility constructor for in-process scripted verifiers; the production v5 adapter always names claims. */
        public Verdict(String support, String prohibitedAdvice) {
            this(prohibitedAdvice, List.of(new ClaimVerdict(null, support, "no")));
        }
    }
}
