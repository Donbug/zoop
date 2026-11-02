package com.zoop.admin.pipeline;

/**
 * {@code startGraphRound}'s body ({@code GraphRoundStartRequest}): the slot to open, or nothing for "now" (the current minute).
 * The body itself is optional.
 */
public record GraphRoundStartRequest(String slotAt) {
}
