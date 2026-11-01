package com.zoop.graph.importer;

import java.io.IOException;
import java.io.InputStream;
import java.util.List;

import org.junit.jupiter.api.Test;
import tools.jackson.databind.JsonNode;

import static org.junit.jupiter.api.Assertions.assertDoesNotThrow;
import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.junit.jupiter.api.Assertions.assertTrue;

/**
 * The original-mention {@code eventTime} grammar against the vector file the producer's own test reads
 * ({@code ai/pipeline/tests/test_handoff_mention_time.py}): both sides accept and refuse exactly the same strings. The vectors are
 * hand-written; nothing is derived from {@link HandoffTime}.
 */
class HandoffMentionTimeTest {
    private static final List<String> PRECISIONS = List.of("unknown", "year", "month", "day", "datetime");
    private static final JsonNode VECTORS = load();

    private static JsonNode load() {
        try (InputStream in = HandoffMentionTimeTest.class.getClassLoader()
                .getResourceAsStream("graph-handoff/mention-time-vectors.json")) {
            return HandoffFixtures.parse(in.readAllBytes());
        } catch (IOException error) {
            throw new IllegalStateException(error);
        }
    }

    private static String text(JsonNode node) {
        return node.isNull() ? null : node.stringValue();
    }

    private static void assertUnsupported(String value, String precision, String message) {
        GraphHandoffException failure = assertThrows(GraphHandoffException.class,
                () -> HandoffTime.mentionEventTime(value, precision), message);
        assertEquals(GraphHandoffFailure.TEMPORAL_UNSUPPORTED, failure.failure(), message);
    }

    @Test
    void theVectorFileIsTheOneTheProducerReads() {
        assertEquals("zoop-mention-time-vectors-1", VECTORS.get("schemaVersion").stringValue());
        assertTrue(VECTORS.get("accept").size() >= 15 && VECTORS.get("reject").size() >= 50);
    }

    @Test
    void everyCalendarFormIsAcceptedOnlyWithItsOwnPrecision() {
        for (JsonNode item : VECTORS.get("accept").values()) {
            String value = text(item.get("value"));
            String precision = item.get("precision").stringValue();
            assertDoesNotThrow(() -> HandoffTime.mentionEventTime(value, precision), String.valueOf(value));
            for (String other : PRECISIONS) {
                if (!other.equals(precision)) {
                    assertUnsupported(value, other, value + " as " + other);
                }
            }
        }
    }

    @Test
    void everythingElseIsUnsupportedUnderEveryStatedPrecisionAndNeverRewritten() {
        for (JsonNode item : VECTORS.get("reject").values()) {
            String value = text(item.get("value"));
            for (String precision : PRECISIONS) {
                assertUnsupported(value, precision, item.get("why").stringValue() + " as " + precision);
            }
        }
    }

    @Test
    void aMissingTimeIsUnknownOnly() {
        assertDoesNotThrow(() -> HandoffTime.mentionEventTime(null, "unknown"));
        for (String precision : List.of("year", "month", "day", "datetime", "hour")) {
            assertUnsupported(null, precision, "null as " + precision);
        }
        assertUnsupported("2026", "hour", "an unknown precision name");
        assertUnsupported("2026", null, "a missing precision");
    }

    @Test
    void unresolvedReceiptValuesRemainOutsideTheStrictCalendarGrammar() {
        for (String value : List.of("10.19일", "'25.8월", "2026-02-30")) {
            assertDoesNotThrow(() -> HandoffTime.receiptEventTime(value, "unresolved"));
            for (String precision : PRECISIONS) assertUnsupported(value, precision, value);
        }
        for (String value : List.of("", "2026-09-30", "2026-09", "2026")) {
            assertThrows(GraphHandoffException.class, () -> HandoffTime.receiptEventTime(value, "unresolved"));
        }
        assertThrows(GraphHandoffException.class, () -> HandoffTime.receiptEventTime(null, "unresolved"));
    }

    @Test
    void sharedGeographyAndRawTimeFixturesAgreeWithPythonAndService() throws IOException {
        try (InputStream in = getClass().getClassLoader().getResourceAsStream("graph-handoff/public-unknown-fields-cases.json")) {
            JsonNode cases = HandoffFixtures.parse(in.readAllBytes());
            for (JsonNode item : cases.get("accept").values()) {
                assertDoesNotThrow(() -> HandoffBundleVerifier.verify(item.get("bundle")), item.get("name").stringValue());
            }
            for (JsonNode item : cases.get("reject").values()) {
                assertThrows(RuntimeException.class, () -> HandoffBundleVerifier.verify(item.get("bundle")), item.get("name").stringValue());
            }
        }
    }
}
