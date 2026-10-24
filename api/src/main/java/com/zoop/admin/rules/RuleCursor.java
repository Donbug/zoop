package com.zoop.admin.rules;

import com.zoop.auth.service.CsrfKeyRing;
import com.zoop.auth.service.SignedCursor;
import com.zoop.common.exception.CustomException;
import com.zoop.common.exception.ErrorCode;
import tools.jackson.databind.ObjectMapper;

/** The {@code listPublicationRules} cursor ({@link SignedCursor}): bound to the admin and the limit. */
final class RuleCursor {
    private static final String PURPOSE = "admin-rule-cursor-v1";

    private RuleCursor() {
    }

    static Position decode(ObjectMapper mapper, CsrfKeyRing keys, String value, String adminId, Integer requestedLimit,
            int maxLimit) {
        try {
            Position position = SignedCursor.decode(mapper, keys, PURPOSE, value, Position.class);
            if (position == null) return null;
            if (!"ar1".equals(position.version()) || !adminId.equals(position.adminId())
                    || position.limit() < 1 || position.limit() > maxLimit
                    || requestedLimit != null && requestedLimit != position.limit() || position.id() == null) {
                throw new IllegalArgumentException();
            }
            return position;
        } catch (Exception exception) {
            throw new CustomException(ErrorCode.INVALID_CURSOR, exception);
        }
    }

    static String encode(ObjectMapper mapper, CsrfKeyRing keys, String adminId, int limit, String id) {
        return SignedCursor.encode(mapper, keys, PURPOSE, new Position("ar1", keys.activeKeyId(), adminId, limit, id));
    }

    /** {@code id} is the last rule of the page. */
    record Position(String version, String keyId, String adminId, int limit, String id) implements SignedCursor.Position {
    }
}
