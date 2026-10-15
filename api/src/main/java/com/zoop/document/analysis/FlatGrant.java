package com.zoop.document.analysis;

import java.util.List;

/**
 * One entry of the operator's flat S1 grant registry ({@code zoop-ai-s1-1}), the same file and shape that
 * {@code ai/service} reads as {@code ZOOP_AI_SERVICE_GRANTS}. {@code expiresAt} is kept as written: it is only parsed when a
 * decision needs it, so that one odd value denies that grant instead of making the whole registry unreadable.
 */
public record FlatGrant(String grantId, String revision, String sourceId, boolean enabled, String rights,
        List<String> allowedOperations, List<String> recipients, List<String> purposes, List<String> evidence,
        String expiresAt) {

    public FlatGrant {
        allowedOperations = List.copyOf(allowedOperations);
        recipients = List.copyOf(recipients);
        purposes = List.copyOf(purposes);
        evidence = List.copyOf(evidence);
    }
}
