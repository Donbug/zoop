package com.zoop.admin.audit;

import java.util.regex.Pattern;

/** A guard for operator-entered reasons; this mirrors the SQL public_reason filter. */
public final class AuditReasonPolicy {
    private static final Pattern SENSITIVE = Pattern.compile(
            "password|token|cookie|authorization|bearer|api[_-]?key|https?://|@|"
                    + "[A-Za-z0-9_-]{32,}", Pattern.CASE_INSENSITIVE);

    private AuditReasonPolicy() { }

    public static boolean safeMemberReason(String reason) {
        return reason != null && !reason.isBlank()
                && reason.chars().noneMatch(Character::isISOControl)
                && !SENSITIVE.matcher(reason).find();
    }
}
