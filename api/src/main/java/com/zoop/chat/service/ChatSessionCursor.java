package com.zoop.chat.service;

import java.time.Instant;

import com.zoop.auth.service.CsrfKeyRing;
import com.zoop.auth.service.SignedCursor;
import com.zoop.common.exception.CustomException;
import com.zoop.common.exception.ErrorCode;
import tools.jackson.databind.ObjectMapper;

/** The {@code listConversations} cursor ({@link SignedCursor}): bound to the member and the page size. */
final class ChatSessionCursor {
    private static final String PURPOSE = "chat-session-cursor-v1";

    private ChatSessionCursor() {
    }

    static Position decode(ObjectMapper mapper, CsrfKeyRing keys, String value, String memberId, int limit) {
        try {
            Position position = SignedCursor.decode(mapper, keys, PURPOSE, value, Position.class);
            if (position == null) return null;
            if (!"cs1".equals(position.version()) || !memberId.equals(position.memberId()) || position.limit() != limit
                    || position.at() == null || position.id() == null) {
                throw new IllegalArgumentException();
            }
            return position;
        } catch (Exception exception) {
            throw new CustomException(ErrorCode.INVALID_CURSOR, exception);
        }
    }

    static String encode(ObjectMapper mapper, CsrfKeyRing keys, String memberId, int limit, Instant at, String id) {
        return SignedCursor.encode(mapper, keys, PURPOSE, new Position("cs1", keys.activeKeyId(), memberId, limit, at, id));
    }

    /** {@code at}/{@code id} are the last row's {@code updated_at} and id. */
    record Position(String version, String keyId, String memberId, int limit, Instant at, String id)
            implements SignedCursor.Position {
    }
}
