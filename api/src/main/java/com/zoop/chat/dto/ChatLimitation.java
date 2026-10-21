package com.zoop.chat.dto;

/** OpenAPI {@code ChatLimitation}: one requirement an answered result did not answer, and why. */
public record ChatLimitation(String kind, String label, String message) {
}
