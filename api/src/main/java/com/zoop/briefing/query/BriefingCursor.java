package com.zoop.briefing.query;

import java.nio.charset.StandardCharsets;
import java.time.Instant;
import java.util.Base64;
import com.zoop.common.exception.CustomException;
import com.zoop.common.exception.ErrorCode;
import com.zoop.briefing.storage.BriefingRound;

/** Versioned keyset; limit is part of the query scope. No row offsets or unpublished contents. */
record BriefingCursor(Instant scheduledAt, String id) {
    static BriefingCursor decode(String value, int limit) {
        try {
            if (value == null) return null;
            if (value.length() > 2048 || value.isBlank()) throw new IllegalArgumentException();
            String text = new String(Base64.getUrlDecoder().decode(value), StandardCharsets.UTF_8);
            String[] fields = text.split("\\n", -1);
            if (fields.length != 4 || !fields[0].equals("br1") || !fields[1].equals(Integer.toString(limit))
                    || fields[3].isBlank() || fields[3].length() > 256) throw new IllegalArgumentException();
            return new BriefingCursor(Instant.parse(fields[2]), fields[3]);
        } catch (RuntimeException e) { throw new CustomException(ErrorCode.INVALID_CURSOR); }
    }
    static String encode(BriefingRound row, int limit) {
        return Base64.getUrlEncoder().withoutPadding().encodeToString(
                ("br1\n" + limit + "\n" + row.scheduledAt() + "\n" + row.id()).getBytes(StandardCharsets.UTF_8));
    }
}
