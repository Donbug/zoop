package com.zoop.briefing.query;

import java.nio.ByteBuffer;
import java.nio.charset.CharacterCodingException;
import java.nio.charset.CodingErrorAction;
import java.nio.charset.StandardCharsets;
import java.time.Instant;
import java.time.ZoneOffset;
import java.util.Base64;
import com.zoop.common.exception.CustomException;
import com.zoop.common.exception.ErrorCode;
import com.zoop.briefing.storage.BriefingHistoryEntry;
import tools.jackson.core.StreamReadConstraints;
import tools.jackson.core.StreamReadFeature;
import tools.jackson.core.json.JsonFactory;
import tools.jackson.databind.json.JsonMapper;
import tools.jackson.databind.DeserializationFeature;

/** Versioned keyset; new JSON envelopes preserve opaque IDs including newlines. br1 remains readable. */
record BriefingCursor(Instant scheduledAt, String id) {
    private static final int MAX_LENGTH = 2048;
    private static final JsonMapper JSON = JsonMapper.builder(JsonFactory.builder()
            .streamReadConstraints(StreamReadConstraints.builder().maxNestingDepth(8).build())
            .enable(StreamReadFeature.STRICT_DUPLICATE_DETECTION).build())
            .enable(DeserializationFeature.FAIL_ON_TRAILING_TOKENS).build();

    static BriefingCursor decode(String value, int limit) {
        try {
            if (value == null) return null;
            if (value.length() > MAX_LENGTH || value.isBlank()) throw new IllegalArgumentException();
            var bytes = Base64.getUrlDecoder().decode(value);
            String text = StandardCharsets.UTF_8.newDecoder().onMalformedInput(CodingErrorAction.REPORT)
                    .onUnmappableCharacter(CodingErrorAction.REPORT).decode(ByteBuffer.wrap(bytes)).toString();
            String time;
            String id;
            if (text.startsWith("br1\n")) {
                String[] fields = text.split("\\n", -1);
                if (fields.length != 4 || !fields[1].equals(Integer.toString(limit)) || fields[3].length() > 256) {
                    throw new IllegalArgumentException();
                }
                time = fields[2]; id = fields[3];
            } else {
                var fields = JSON.readTree(text);
                if (!fields.isArray() || fields.size() != 4 || !fields.get(0).isString()
                        || !fields.get(0).stringValue().equals("br2") || !fields.get(1).isIntegralNumber()
                        || !fields.get(1).canConvertToInt() || fields.get(1).intValue() != limit
                        || !fields.get(2).isString() || !fields.get(3).isString()) {
                    throw new IllegalArgumentException();
                }
                time = fields.get(2).stringValue(); id = fields.get(3).stringValue();
            }
            if (id.isBlank() || !StandardCharsets.UTF_8.newEncoder().canEncode(id)) throw new IllegalArgumentException();
            Instant position = Instant.parse(time);
            int year = position.atOffset(ZoneOffset.UTC).getYear();
            // Public timestamps use four-digit RFC3339 dates; larger Instants can overflow PostgreSQL bindings.
            if (year < 1 || year > 9999) throw new IllegalArgumentException();
            return new BriefingCursor(position, id);
        } catch (RuntimeException | CharacterCodingException e) {
            throw new CustomException(ErrorCode.INVALID_CURSOR);
        }
    }

    static String encode(BriefingHistoryEntry row, int limit) {
        var fields = JSON.createArrayNode().add("br2").add(limit).add(row.scheduledAt().toString()).add(row.id());
        return Base64.getUrlEncoder().withoutPadding().encodeToString(JSON.writeValueAsBytes(fields));
    }
}
