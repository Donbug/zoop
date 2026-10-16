package com.zoop.briefing.query;

import com.zoop.briefing.storage.BriefingHistoryEntry;
import com.zoop.common.exception.CustomException;
import com.zoop.common.exception.ErrorCode;
import java.nio.charset.StandardCharsets;
import java.time.Instant;
import java.time.LocalDate;
import java.util.Base64;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.params.ParameterizedTest;
import org.junit.jupiter.params.provider.ValueSource;
import static org.junit.jupiter.api.Assertions.*;

class BriefingCursorTest {
    private static final Instant TIME = Instant.parse("2026-10-13T00:20:00.123456Z");
    private static String token(String text) {
        return Base64.getUrlEncoder().withoutPadding().encodeToString(text.getBytes(StandardCharsets.UTF_8));
    }

    @Test void opaqueIdsRoundTripWithoutDelimiterAssumptions() {
        for (String id : new String[]{"normal", "한글·회차\n두 번째 줄", "quote\"and\\slash", "a".repeat(300)}) {
            var row = new BriefingHistoryEntry(id, LocalDate.of(2026, 10, 13), "morning", TIME, "published", TIME);
            var decoded = BriefingCursor.decode(BriefingCursor.encode(row, 20), 20);
            assertEquals(id, decoded.id()); assertEquals(TIME, decoded.scheduledAt());
        }
    }
    @Test void existingBr1CursorsRemainReadable() {
        var decoded = BriefingCursor.decode(token("br1\n20\n" + TIME + "\nexisting-id"), 20);
        assertEquals("existing-id", decoded.id()); assertEquals(TIME, decoded.scheduledAt());
    }
    @Test void invalidUtf8CannotBeReplacedAndTreatedAsAnId() {
        byte[] prefix = "br1\n20\n2026-10-13T00:20:00Z\n".getBytes(StandardCharsets.UTF_8);
        byte[] bytes = java.util.Arrays.copyOf(prefix, prefix.length + 1); bytes[bytes.length - 1] = (byte) 0xFF;
        assertInvalid(Base64.getUrlEncoder().withoutPadding().encodeToString(bytes));
    }
    @ParameterizedTest
    @ValueSource(strings = {
        "[]", "null", "{}", "[\"br2\",20,\"2026-10-13T00:20:00Z\",\"id\"] {}", "[\"br3\",20,\"2026-10-13T00:20:00Z\",\"id\"]",
        "[\"br2\",21,\"2026-10-13T00:20:00Z\",\"id\"]",
        "[\"br2\",20.0,\"2026-10-13T00:20:00Z\",\"id\"]",
        "[\"br2\",20,\"+999999999-01-01T00:00:00Z\",\"id\"]",
        "[\"br2\",20,\"2026-10-13T00:20:00Z\",null]",
        "[\"br2\",20,\"2026-10-13T00:20:00Z\",\"   \"]",
        "[\"br2\",20,\"no-time\",\"id\"]",
        "br1\n21\n2026-10-13T00:20:00Z\nid"
    })
    void rejectsMalformedOrOutOfScopeCursors(String text) { assertInvalid(token(text)); }
    private static void assertInvalid(String value) {
        assertEquals(ErrorCode.INVALID_CURSOR, assertThrows(CustomException.class, () -> BriefingCursor.decode(value, 20)).getErrorCode());
    }
}
