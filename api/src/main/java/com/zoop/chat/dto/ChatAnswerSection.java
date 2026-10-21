package com.zoop.chat.dto;

import java.util.List;

/** OpenAPI {@code ChatAnswerSection}: one part of an answer at a single basis level. */
public record ChatAnswerSection(String basis, String text, List<String> evidenceIds) {
}
