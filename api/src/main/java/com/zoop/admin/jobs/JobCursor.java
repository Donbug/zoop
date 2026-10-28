package com.zoop.admin.jobs;

import com.zoop.auth.service.CsrfKeyRing;
import com.zoop.auth.service.SignedCursor;
import com.zoop.common.exception.CustomException;
import com.zoop.common.exception.ErrorCode;
import java.time.Instant;
import tools.jackson.databind.ObjectMapper;

/** The {@code listAnalysisJobs} cursor ({@link SignedCursor}): bound to the admin, the status filter and the limit. */
final class JobCursor {
    private static final String PURPOSE = "admin-job-cursor-v1";

    private JobCursor() {
    }

    static Position decode(ObjectMapper mapper, CsrfKeyRing keys, String value, String adminId, String status,
            Integer requestedLimit, int maxLimit) {
        try {
            Position position = SignedCursor.decode(mapper, keys, PURPOSE, value, Position.class);
            if (position == null) return null;
            if (!"aj1".equals(position.version()) || !adminId.equals(position.adminId())
                    || !String.valueOf(status).equals(position.status())
                    || position.limit() < 1 || position.limit() > maxLimit
                    || requestedLimit != null && requestedLimit != position.limit()
                    || position.at() == null || position.id() == null) {
                throw new IllegalArgumentException();
            }
            return position;
        } catch (Exception exception) {
            throw new CustomException(ErrorCode.INVALID_CURSOR, exception);
        }
    }

    static String encode(ObjectMapper mapper, CsrfKeyRing keys, String adminId, String status, int limit, Instant at,
            String id) {
        return SignedCursor.encode(mapper, keys, PURPOSE,
                new Position("aj1", keys.activeKeyId(), adminId, String.valueOf(status), limit, at, id));
    }

    /** {@code status} is the filter as text ("null" for none); {@code at}/{@code id} are the last row's requested_at and id. */
    record Position(String version, String keyId, String adminId, String status, int limit, Instant at, String id)
            implements SignedCursor.Position {
    }
}
