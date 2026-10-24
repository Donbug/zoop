package com.zoop.admin.audit;

import java.time.Instant;

import com.zoop.auth.service.CsrfKeyRing;
import com.zoop.auth.service.SignedCursor;
import com.zoop.common.exception.CustomException;
import com.zoop.common.exception.ErrorCode;
import tools.jackson.databind.ObjectMapper;

final class AuditCursor {
    private static final String PURPOSE = "admin-audit-cursor-v1";

    private AuditCursor() { }

    static Position decode(ObjectMapper mapper, CsrfKeyRing keys, String value,
            String adminId, String filtersHash, Integer requestedLimit, Instant now) {
        try {
            Position position = SignedCursor.decode(mapper, keys, PURPOSE, value, Position.class);
            if (position == null) return null;
            if (!"aa1".equals(position.version())
                    || !adminId.equals(position.adminId()) || !filtersHash.equals(position.filtersHash())
                    || position.limit() < 1 || position.limit() > 100
                    || requestedLimit != null && requestedLimit != position.limit()
                    || position.asOf() == null || position.at() == null || position.id() < 1
                    || position.at().isAfter(position.asOf()) || position.asOf().isAfter(now)) {
                throw new IllegalArgumentException();
            }
            return position;
        } catch (Exception exception) {
            throw new CustomException(ErrorCode.INVALID_CURSOR, exception);
        }
    }

    static String encode(ObjectMapper mapper, CsrfKeyRing keys, String adminId,
            String filtersHash, int limit, Instant asOf, Instant at, long id) {
        return SignedCursor.encode(mapper, keys, PURPOSE, new Position("aa1", keys.activeKeyId(), adminId, filtersHash,
                limit, asOf, at, id));
    }

    record Position(String version, String keyId, String adminId, String filtersHash,
            int limit, Instant asOf, Instant at, long id) implements SignedCursor.Position { }
}
