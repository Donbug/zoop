package com.zoop.graph.read;

import java.util.Arrays;
import java.util.List;
import java.util.Map;
import java.util.regex.Pattern;

/**
 * Korean text for an article role (prototype {@code summaries.role_label}/{@code role_display}). Korean is kept,
 * known English vocabulary is translated, and an unknown phrase is never guessed. The snapshot keeps the raw role.
 */
final class RoleLabels {
    // shortcut: only the five roles seen in the AI golden data, extend when the AI role vocabulary is handed over.
    static final Map<String, String> KO = Map.of(
            "builder", "구축사",
            "host", "주최자",
            "investee", "투자 대상",
            "investor", "투자사",
            "issuer", "발행사");
    static final int MAX_CHARS = 14;
    private static final Pattern HANGUL = Pattern.compile("[가-힣]");

    private RoleLabels() {
    }

    /** Short Korean label, or null when it cannot be shown without guessing. */
    static String label(String role) {
        if (role == null) return null;
        String clause = role.split("[,;]", 2)[0].strip();
        if (clause.isEmpty()) return null;
        if (HANGUL.matcher(clause).find()) {
            return clause.length() <= MAX_CHARS ? clause : clause.substring(0, MAX_CHARS - 1).stripTrailing() + "…";
        }
        List<String> parts = Arrays.stream(clause.split("(?i)/|\\s+and\\s+"))
                .map(p -> p.replaceAll("[\\s_-]+", " ").strip().toLowerCase()).toList();
        return parts.stream().allMatch(KO::containsKey)
                ? String.join("·", parts.stream().map(KO::get).toList()) : null;
    }

    /** Detail text: the Korean label when known, otherwise the article's original text unchanged. */
    static String display(String role) {
        String label = label(role);
        return label != null ? label : role;
    }
}
