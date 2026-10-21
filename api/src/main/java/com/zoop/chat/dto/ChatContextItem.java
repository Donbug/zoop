package com.zoop.chat.dto;

/** OpenAPI {@code ChatContextItem}: one selected company, issue, edge or evidence with its display label. */
public record ChatContextItem(String id, String kind, String label) {
}
