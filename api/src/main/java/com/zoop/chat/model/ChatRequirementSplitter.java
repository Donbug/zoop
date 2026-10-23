package com.zoop.chat.model;

import java.util.ArrayList;
import java.util.List;
import java.util.regex.Pattern;

/**
 * The deterministic requirement splitter (provisional decision of 2026-10-22, implementation plan stage 3): a question is split
 * only at unambiguous boundaries, question marks, line breaks, semicolons and the stand-alone conjunctions "그리고" and "또한",
 * and when nothing splits it the whole question is one requirement. It never splits inside a phrase such as "공급하고", so a
 * compound sentence it cannot separate safely stays one requirement for the router to tag with several Q types.
 */
public final class ChatRequirementSplitter {
    /** One explicit requirement: a stable id within the run and the member's own words. */
    public record Piece(String id, String text) { }

    private static final Pattern BOUNDARY = Pattern.compile("[?？;\\n]+|\\s+(?:그리고|또한)\\s+");
    private static final int MIN_LENGTH = 2;

    private ChatRequirementSplitter() {
    }

    public static List<Piece> split(String question) {
        List<String> parts = new ArrayList<>();
        for (String part : BOUNDARY.split(question.strip())) {
            String text = part.strip();
            if (text.codePointCount(0, text.length()) >= MIN_LENGTH) parts.add(text);
        }
        if (parts.isEmpty()) parts.add(question.strip());
        List<Piece> pieces = new ArrayList<>();
        for (int i = 0; i < parts.size(); i++) pieces.add(new Piece("r" + (i + 1), parts.get(i)));
        return List.copyOf(pieces);
    }
}
