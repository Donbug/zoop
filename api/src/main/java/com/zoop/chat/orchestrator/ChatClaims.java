package com.zoop.chat.orchestrator;

import java.text.BreakIterator;
import java.util.ArrayList;
import java.util.List;
import java.util.Locale;

/**
 * The deterministic claim boundary shared by the application and the semantic-verification request. Claim ids are positional
 * inside a checked section and never come from the model. Empty sentence fragments are ignored; more than twenty claims are
 * refused before verification so the Jev question count stays bounded.
 */
public final class ChatClaims {
    public static final int MAX_PER_SECTION = 20;

    private ChatClaims() {
    }

    public record Claim(String id, String text) { }

    public static List<Claim> split(int sectionIndex, String text) {
        if (sectionIndex < 0 || sectionIndex > 11 || text == null || text.isBlank()) {
            throw new IllegalArgumentException("invalid claim source");
        }
        BreakIterator sentences = BreakIterator.getSentenceInstance(Locale.KOREAN);
        sentences.setText(text);
        List<Claim> claims = new ArrayList<>();
        int start = sentences.first();
        for (int end = sentences.next(); end != BreakIterator.DONE; start = end, end = sentences.next()) {
            String claim = text.substring(start, end).strip();
            if (claim.isEmpty()) continue;
            if (claims.size() == MAX_PER_SECTION) throw new IllegalArgumentException("too many claims");
            claims.add(new Claim("s" + sectionIndex + "c" + claims.size(), claim));
        }
        if (claims.isEmpty()) throw new IllegalArgumentException("answer section has no claim");
        return List.copyOf(claims);
    }
}
