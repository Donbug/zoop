package com.zoop.chat.dto;

/** OpenAPI {@code ChatAppliedPeriod}: the period used and where it came from (question, context or evidence). */
public record ChatAppliedPeriod(String start, String end, String basis, String expression) {
}
