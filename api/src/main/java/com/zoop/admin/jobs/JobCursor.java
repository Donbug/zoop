package com.zoop.admin.jobs;

import com.zoop.auth.service.CsrfKeyRing;
import com.zoop.common.exception.CustomException;
import com.zoop.common.exception.ErrorCode;
import java.security.MessageDigest;
import java.time.Instant;
import java.util.Base64;
import tools.jackson.databind.ObjectMapper;

/** The signed {@code listAnalysisJobs} cursor (the audit cursor's form): bound to the admin, the status filter and the limit. */
final class JobCursor {
    private static final String PURPOSE = "admin-job-cursor-v1";
    private static final int MAX_LENGTH = 4096;

    private JobCursor() {
    }

    static Position decode(ObjectMapper mapper, CsrfKeyRing keys, String value, String adminId, String status,
            Integer requestedLimit, int maxLimit) {
        try {
            if (value == null) return null;
            if (value.isBlank() || value.length() > MAX_LENGTH) throw new IllegalArgumentException();
            String[] parts = value.split("[.]", -1);
            if (parts.length != 2) throw new IllegalArgumentException();
            byte[] payload = Base64.getUrlDecoder().decode(parts[0]);
            byte[] signature = Base64.getUrlDecoder().decode(parts[1]);
            Position position = mapper.readValue(payload, Position.class);
            if (position == null || !"aj1".equals(position.version()) || !adminId.equals(position.adminId())
                    || !String.valueOf(status).equals(position.status())
                    || position.limit() < 1 || position.limit() > maxLimit
                    || requestedLimit != null && requestedLimit != position.limit()
                    || position.at() == null || position.id() == null
                    || position.keyId() == null || !position.keyId().matches("[A-Za-z0-9_-]{1,64}")) {
                throw new IllegalArgumentException();
            }
            byte[] expected = keys.sign(position.keyId(), PURPOSE, payload).orElseThrow(IllegalArgumentException::new);
            if (!MessageDigest.isEqual(expected, signature)) throw new IllegalArgumentException();
            return position;
        } catch (Exception exception) {
            throw new CustomException(ErrorCode.INVALID_CURSOR, exception);
        }
    }

    static String encode(ObjectMapper mapper, CsrfKeyRing keys, String adminId, String status, int limit, Instant at,
            String id) {
        try {
            var position = new Position("aj1", keys.activeKeyId(), adminId, String.valueOf(status), limit, at, id);
            byte[] payload = mapper.writeValueAsBytes(position);
            byte[] signature = keys.sign(position.keyId(), PURPOSE, payload).orElseThrow();
            return Base64.getUrlEncoder().withoutPadding().encodeToString(payload) + "."
                    + Base64.getUrlEncoder().withoutPadding().encodeToString(signature);
        } catch (Exception exception) {
            throw new IllegalStateException("Unable to encode job cursor", exception);
        }
    }

    /** {@code status} is the filter as text ("null" for none); {@code at}/{@code id} are the last row's requested_at and id. */
    record Position(String version, String keyId, String adminId, String status, int limit, Instant at, String id) {
    }
}
