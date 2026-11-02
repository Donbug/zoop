package com.zoop.admin.briefings;

import com.zoop.auth.service.CsrfKeyRing;
import com.zoop.auth.service.SignedCursor;
import com.zoop.common.exception.CustomException;
import com.zoop.common.exception.ErrorCode;
import java.time.Instant;
import java.util.Objects;
import tools.jackson.databind.ObjectMapper;

final class AdminBriefingCursor {
    private static final String PURPOSE = "admin-briefing-rounds-v1";
    private AdminBriefingCursor() { }

    static Position decode(ObjectMapper mapper, CsrfKeyRing keys, String token, String admin, String from, String to,
            Integer limit) {
        try {
            Position p = SignedCursor.decode(mapper, keys, PURPOSE, token, Position.class);
            if (p == null) return null;
            if (!"abr1".equals(p.version()) || !admin.equals(p.adminId()) || !Objects.equals(from, p.from())
                    || !Objects.equals(to, p.to()) || p.limit() < 1 || p.limit() > 100
                    || limit != null && limit != p.limit() || p.at() == null || p.id() == null || p.id().isBlank()) {
                throw new IllegalArgumentException();
            }
            return p;
        } catch (Exception error) { throw new CustomException(ErrorCode.INVALID_CURSOR, error); }
    }

    static String encode(ObjectMapper mapper, CsrfKeyRing keys, String admin, String from, String to, int limit,
            Instant at, String id) {
        return SignedCursor.encode(mapper, keys, PURPOSE,
                new Position("abr1", keys.activeKeyId(), admin, from, to, limit, at, id));
    }

    record Position(String version, String keyId, String adminId, String from, String to, int limit, Instant at, String id)
            implements SignedCursor.Position { }
}
