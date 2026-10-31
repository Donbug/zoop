package com.zoop.chat.dto;

import java.time.Instant;
import java.util.List;

/**
 * OpenAPI {@code ChatUiAction}: something the member can open from an answer, offered by the server from what the answered
 * requirements actually read. It runs only on the member's click; the screen it opens rechecks access.
 */
public record ChatUiAction(String actionId, String kind, String label, List<String> requirementIds, Target target) {
    public static final String OPEN_COMPANY = "open_company";
    public static final String FOCUS_PATH = "focus_path";
    public static final String OPEN_BRIEFING = "open_briefing";

    /** OpenAPI {@code ChatUiActionTarget}: only the fields of the action's kind are set. */
    public record Target(String companyId, String fromId, String toId, String date, String edition, String graphVersion,
            Instant asOf) {
        public static Target company(String id) {
            return new Target(id, null, null, null, null, null, null);
        }

        public static Target path(String fromId, String toId, String graphVersion, Instant asOf) {
            return new Target(null, fromId, toId, null, null, graphVersion, asOf);
        }

        public static Target briefing(String date, String edition) {
            return new Target(null, null, null, date, edition, null, null);
        }
    }
}
