package com.zoop.admin.members.service;

import java.time.Instant;
import java.time.ZoneOffset;
import java.util.Base64;

import com.zoop.common.exception.CustomException;
import com.zoop.common.exception.ErrorCode;
import tools.jackson.databind.ObjectMapper;

final class MemberListCursor {
    private static final int MAX_LENGTH = 2048;

    private MemberListCursor() { }

    static Position decode(ObjectMapper mapper, String value, String filterHash, Integer requestedLimit) {
        try {
            if (value == null) return null;
            if (value.isBlank() || value.length() > MAX_LENGTH) throw new IllegalArgumentException();
            Position position = mapper.readValue(Base64.getUrlDecoder().decode(value), Position.class);
            if (!"am1".equals(position.version()) || !filterHash.equals(position.filterHash())
                    || position.limit() < 1 || position.limit() > 100
                    || requestedLimit != null && requestedLimit != position.limit()
                    || position.asOf() == null || position.createdAt() == null
                    || position.id() == null || position.id().isBlank() || position.id().length() > 256) {
                throw new IllegalArgumentException();
            }
            int asOfYear = position.asOf().atOffset(ZoneOffset.UTC).getYear();
            int createdYear = position.createdAt().atOffset(ZoneOffset.UTC).getYear();
            if (asOfYear < 1 || asOfYear > 9999 || createdYear < 1 || createdYear > 9999
                    || position.createdAt().isAfter(position.asOf())) {
                throw new IllegalArgumentException();
            }
            return position;
        } catch (CustomException exception) {
            throw exception;
        } catch (Exception exception) {
            throw new CustomException(ErrorCode.INVALID_CURSOR, exception);
        }
    }

    static String encode(ObjectMapper mapper, String filterHash, int limit, Instant asOf,
            Instant createdAt, String id) {
        try {
            return Base64.getUrlEncoder().withoutPadding().encodeToString(
                    mapper.writeValueAsBytes(new Position("am1", filterHash, limit, asOf, createdAt, id)));
        } catch (Exception exception) {
            throw new IllegalStateException("Unable to encode member cursor", exception);
        }
    }

    record Position(String version, String filterHash, int limit, Instant asOf, Instant createdAt, String id) { }
}
