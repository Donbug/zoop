package com.zoop.chat.dto;

/** OpenAPI {@code ChatChoice}: an option of a clarification; {@code id} is opaque and returned as is. */
public record ChatChoice(String id, String label, String kind) {
}
