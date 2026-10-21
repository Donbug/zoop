package com.zoop.admin.audit;

import java.security.MessageDigest;
import java.time.Instant;
import java.util.Base64;

import com.zoop.auth.service.CsrfKeyRing;
import com.zoop.common.exception.CustomException;
import com.zoop.common.exception.ErrorCode;
import tools.jackson.databind.ObjectMapper;

final class AuditCursor {
    private static final String PURPOSE = "admin-audit-cursor-v1";
    private static final int MAX_LENGTH = 4096;

    private AuditCursor() { }

    static Position decode(ObjectMapper mapper, CsrfKeyRing keys, String value,
            String adminId, String filtersHash, Integer requestedLimit, Instant now) {
        try {
            if (value == null) return null;
            if (value.isBlank() || value.length() > MAX_LENGTH) throw new IllegalArgumentException();
            String[] parts = value.split("[.]", -1);
            if (parts.length != 2) throw new IllegalArgumentException();
            byte[] payload = Base64.getUrlDecoder().decode(parts[0]);
            byte[] signature = Base64.getUrlDecoder().decode(parts[1]);
            Position position = mapper.readValue(payload, Position.class);
            if (position == null || !"aa1".equals(position.version())
                    || !adminId.equals(position.adminId()) || !filtersHash.equals(position.filtersHash())
                    || position.limit() < 1 || position.limit() > 100
                    || requestedLimit != null && requestedLimit != position.limit()
                    || position.asOf() == null || position.at() == null || position.id() < 1
                    || position.at().isAfter(position.asOf()) || position.asOf().isAfter(now)
                    || position.keyId() == null || !position.keyId().matches("[A-Za-z0-9_-]{1,64}")) {
                throw new IllegalArgumentException();
            }
            byte[] expected = keys.sign(position.keyId(), PURPOSE, payload)
                    .orElseThrow(IllegalArgumentException::new);
            if (!MessageDigest.isEqual(expected, signature)) throw new IllegalArgumentException();
            return position;
        } catch (Exception exception) {
            throw new CustomException(ErrorCode.INVALID_CURSOR, exception);
        }
    }

    static String encode(ObjectMapper mapper, CsrfKeyRing keys, String adminId,
            String filtersHash, int limit, Instant asOf, Instant at, long id) {
        try {
            var position = new Position("aa1", keys.activeKeyId(), adminId, filtersHash,
                    limit, asOf, at, id);
            byte[] payload = mapper.writeValueAsBytes(position);
            byte[] signature = keys.sign(position.keyId(), PURPOSE, payload).orElseThrow();
            return Base64.getUrlEncoder().withoutPadding().encodeToString(payload) + "."
                    + Base64.getUrlEncoder().withoutPadding().encodeToString(signature);
        } catch (Exception exception) {
            throw new IllegalStateException("Unable to encode audit cursor", exception);
        }
    }

    record Position(String version, String keyId, String adminId, String filtersHash,
            int limit, Instant asOf, Instant at, long id) { }
}
