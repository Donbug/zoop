package com.zoop.admin.review;

import java.time.Instant;

import com.zoop.auth.service.CsrfKeyRing;
import com.zoop.auth.service.SignedCursor;
import com.zoop.common.exception.CustomException;
import com.zoop.common.exception.ErrorCode;
import tools.jackson.databind.ObjectMapper;

/**
 * The {@code listAnalysisCandidates} cursor ({@link SignedCursor}): bound to the admin, every filter and the limit. Rows are
 * ordered by their last sync time (newest first), so a candidate the sync refreshes while an admin pages moves to the first
 * page: later pages of the same walk do not show it. The list's {@code asOf} tells when the walk started.
 */
final class CandidateCursor {
    private static final String PURPOSE = "admin-candidate-cursor-v1";

    private CandidateCursor() {
    }

    /** {@code filters} is the canonical text of every filter of the request. */
    static Position decode(ObjectMapper mapper, CsrfKeyRing keys, String value, String adminId, String filters,
            Integer requestedLimit, int maxLimit) {
        try {
            Position position = SignedCursor.decode(mapper, keys, PURPOSE, value, Position.class);
            if (position == null) return null;
            if (!"ac1".equals(position.version()) || !adminId.equals(position.adminId())
                    || !filters.equals(position.filters()) || position.limit() < 1 || position.limit() > maxLimit
                    || requestedLimit != null && requestedLimit != position.limit()
                    || position.at() == null || position.id() == null) {
                throw new IllegalArgumentException();
            }
            return position;
        } catch (Exception exception) {
            throw new CustomException(ErrorCode.INVALID_CURSOR, exception);
        }
    }

    static String encode(ObjectMapper mapper, CsrfKeyRing keys, String adminId, String filters, int limit, Instant at,
            String id) {
        return SignedCursor.encode(mapper, keys, PURPOSE,
                new Position("ac1", keys.activeKeyId(), adminId, filters, limit, at, id));
    }

    /** {@code at}/{@code id} are the last row's {@code updated_at} and id. */
    record Position(String version, String keyId, String adminId, String filters, int limit, Instant at, String id)
            implements SignedCursor.Position {
    }
}
