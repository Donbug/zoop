package com.zoop.chat.orchestrator;

import java.util.List;

/**
 * The semantic verifier's verdict per section, in section order ({@code ChatSemanticVerification}, after the S1 thresholds).
 * {@code support} is {@code supported}, {@code contradicted} or {@code hold} for an evidence section and null for a
 * {@code general_knowledge} section, which is never fact-checked. {@code prohibitedAdvice} is {@code no}, {@code yes} or
 * {@code hold} for every section.
 */
public record ChatSemanticVerdicts(List<Verdict> sections) {
    public ChatSemanticVerdicts {
        sections = sections == null ? List.of() : List.copyOf(sections);
    }

    public record Verdict(String support, String prohibitedAdvice) { }
}
