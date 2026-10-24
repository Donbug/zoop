package com.zoop.auth.service;

import java.nio.charset.StandardCharsets;
import java.util.Base64;

import org.junit.jupiter.api.Test;
import tools.jackson.databind.ObjectMapper;
import tools.jackson.databind.json.JsonMapper;

import static org.junit.jupiter.api.Assertions.*;

class SignedCursorTest {
    private static final String RULES = "admin-rule-cursor-v1";
    private static final String AUDIT = "admin-audit-cursor-v1";
    private static final String JOBS = "admin-job-cursor-v1";

    private final ObjectMapper mapper = JsonMapper.builder().build();
    private final CsrfKeyRing keys = new CsrfKeyRing("test", "test=AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA");

    @Test
    void roundTripsUnderItsOwnPurpose() {
        String cursor = SignedCursor.encode(mapper, keys, RULES, new Position("test", "admin-1", 2));

        assertEquals(new Position("test", "admin-1", 2), SignedCursor.decode(mapper, keys, RULES, cursor, Position.class));
        assertNull(SignedCursor.decode(mapper, keys, RULES, null, Position.class));
    }

    @Test
    void oneListsCursorNeverVerifiesAsAnothers() {
        String rules = SignedCursor.encode(mapper, keys, RULES, new Position("test", "admin-1", 2));
        String audit = SignedCursor.encode(mapper, keys, AUDIT, new Position("test", "admin-1", 2));

        assertThrows(IllegalArgumentException.class, () -> SignedCursor.decode(mapper, keys, AUDIT, rules, Position.class));
        assertThrows(IllegalArgumentException.class, () -> SignedCursor.decode(mapper, keys, JOBS, rules, Position.class));
        assertThrows(IllegalArgumentException.class, () -> SignedCursor.decode(mapper, keys, RULES, audit, Position.class));
    }

    @Test
    void rejectsTamperedOrForeignCursors() {
        String cursor = SignedCursor.encode(mapper, keys, RULES, new Position("test", "admin-1", 2));
        String[] parts = cursor.split("[.]");
        String forged = encoded("{\"keyId\":\"test\",\"adminId\":\"admin-2\",\"limit\":2}");
        String unknownKey = encoded("{\"keyId\":\"gone\",\"adminId\":\"admin-1\",\"limit\":2}");

        for (String value : new String[] {
                forged + "." + parts[1],
                parts[0] + "." + encoded("not the mac"),
                unknownKey + "." + parts[1],
                parts[0],
                cursor + ".x",
                "",
                "a".repeat(4097)}) {
            assertThrows(IllegalArgumentException.class,
                    () -> SignedCursor.decode(mapper, keys, RULES, value, Position.class), value);
        }
    }

    private static String encoded(String value) {
        return Base64.getUrlEncoder().withoutPadding().encodeToString(value.getBytes(StandardCharsets.UTF_8));
    }

    record Position(String keyId, String adminId, int limit) implements SignedCursor.Position {
    }
}
