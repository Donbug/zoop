package com.zoop.graph.importer;

import java.io.IOException;
import java.io.InputStream;

import org.junit.jupiter.api.Test;
import tools.jackson.databind.JsonNode;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertTrue;

/**
 * The {@code issues[].summary.generatedAt} grammar against the vector file the producer's own test reads
 * ({@code ai/pipeline/tests/test_issue_summary_contracts.py}): both sides accept and refuse exactly the same values. The vectors are
 * hand-written; nothing is derived from {@link HandoffIssueSummary}, and a library parser is deliberately not the oracle.
 */
class HandoffSummaryTimeTest {
    private static final JsonNode VECTORS = load();

    private static JsonNode load() {
        try (InputStream in = HandoffSummaryTimeTest.class.getClassLoader()
                .getResourceAsStream("graph-handoff/summary-time-vectors.json")) {
            return HandoffFixtures.parse(in.readAllBytes());
        } catch (IOException error) {
            throw new IllegalStateException(error);
        }
    }

    @Test
    void theVectorFileIsTheOneTheProducerReads() {
        assertEquals("zoop-summary-time-vectors-1", VECTORS.get("schemaVersion").stringValue());
        assertTrue(VECTORS.get("accept").size() >= 20 && VECTORS.get("reject").size() >= 60);
    }

    @Test
    void everyAcceptedFormIsAccepted() {
        for (JsonNode value : VECTORS.get("accept").values()) {
            assertTrue(HandoffIssueSummary.generatedAt(value.stringValue()), value.stringValue());
        }
    }

    @Test
    void everythingElseIsRefusedAndAValueThatIsNotATextNeverIs() {
        for (JsonNode item : VECTORS.get("reject").values()) {
            JsonNode value = item.get("value");
            String why = item.get("why").stringValue();
            if (value.isString()) {
                assertFalse(HandoffIssueSummary.generatedAt(value.stringValue()), why + ": " + value.stringValue());
            } else {
                assertFalse(HandoffIssueSummary.generatedAt(null), why);
            }
        }
    }
}
