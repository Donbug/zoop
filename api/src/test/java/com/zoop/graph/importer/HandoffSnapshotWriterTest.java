package com.zoop.graph.importer;

import java.io.IOException;
import java.io.InputStream;
import java.util.List;

import com.zoop.common.json.Canonical;
import com.zoop.graph.importer.HandoffExportParser.VerifiedHandoff;
import com.zoop.graph.snapshot.GraphSnapshotCodec;
import com.zoop.graph.snapshot.PublicGraphSnapshot;
import org.junit.jupiter.api.Test;
import tools.jackson.databind.JsonNode;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertNull;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.junit.jupiter.api.Assertions.assertTrue;

class HandoffSnapshotWriterTest {
    @Test
    void theVersionIdIsADeterministicHashThatAlwaysFitsTheColumn() {
        String longest = "h".repeat(200);

        String id = HandoffSnapshotWriter.versionId(longest);

        assertEquals("gv-" + Canonical.sha256(longest), id);
        assertEquals(67, id.length());
        assertTrue(id.matches("[A-Za-z0-9._:-]{1,120}"));
        assertEquals(id, HandoffSnapshotWriter.versionId(longest));
        assertTrue(!id.equals(HandoffSnapshotWriter.versionId("h".repeat(199))));
    }

    @Test
    void latestPublishedComparesADateAndAnInstantByWhenEachStartsToCount() {
        // A date counts from 12:00 UTC of the NEXT day (the last time zone has left it); an instant counts from itself.
        assertEquals("2026-09-30", HandoffSnapshotWriter.latestPublished(List.of("2026-09-30", "2026-09-30T13:00:00Z")));
        assertEquals("2026-10-02T00:00:00Z", HandoffSnapshotWriter.latestPublished(List.of("2026-09-30", "2026-10-02T00:00:00Z")));
        assertEquals("2026-10-02T00:00:00Z", HandoffSnapshotWriter.latestPublished(List.of("2026-10-02T00:00:00Z", "2026-09-30")));
        // The same moment: the larger text wins, whatever the iteration order.
        assertEquals("2026-10-01T12:00:00Z", HandoffSnapshotWriter.latestPublished(List.of("2026-09-30", "2026-10-01T12:00:00Z")));
        assertEquals("2026-10-01T12:00:00Z", HandoffSnapshotWriter.latestPublished(List.of("2026-10-01T12:00:00Z", "2026-09-30")));
        // One unknown publication time makes the issue never count before an asOf.
        java.util.ArrayList<String> withUnknown = new java.util.ArrayList<>(List.of("2026-09-30"));
        withUnknown.add(null);
        assertNull(HandoffSnapshotWriter.latestPublished(withUnknown));
        assertNull(HandoffSnapshotWriter.latestPublished(List.of()));
    }

    @Test
    void eventTimesKeepTheirStatedPrecisionAndNothingIsInvented() {
        assertNull(HandoffTime.eventTime(null, "unknown"));
        assertEquals("2026", HandoffTime.eventTime("2026", "year"));
        assertEquals("2026-09", HandoffTime.eventTime("2026-09", "month"));
        assertEquals("2026-09-30", HandoffTime.eventTime("2026-09-30", "day"));
        assertEquals("2026-09-30T00:00:00Z", HandoffTime.eventTime("2026-09-30T09:00:00+09:00", "datetime"));
        for (String[] unsupported : new String[][] {{"2026-09-30", "unknown"}, {null, "day"}, {"2026-09", "day"},
                {"2026-9-30", "day"}, {"2026-02-30", "day"}, {"26", "year"}, {"2026-13", "month"},
                {"2026-09-30T09", "datetime"}, {"2026-09-30T09:00:00", "datetime"}, {"2026-09-30", "datetime"},
                {"2026-W40-1", "day"}, {"2026", "century"}}) {
            GraphHandoffException failure = assertThrows(GraphHandoffException.class,
                    () -> HandoffTime.eventTime(unsupported[0], unsupported[1]), String.join("|", String.valueOf(unsupported[0]), unsupported[1]));
            assertEquals(GraphHandoffFailure.TEMPORAL_UNSUPPORTED, failure.failure());
        }
    }

    @Test
    void validityDaysAreWrittenVerbatimOrNotAtAll() {
        assertNull(HandoffTime.dayOrNull(null));
        assertEquals("2026-12-31", HandoffTime.dayOrNull("2026-12-31"));
        for (String bad : List.of("2026-12", "2026", "2026-12-31T00:00:00Z", "2026-W40-1", "20261231", "2026-1-1")) {
            assertEquals(GraphHandoffFailure.TEMPORAL_UNSUPPORTED,
                    assertThrows(GraphHandoffException.class, () -> HandoffTime.dayOrNull(bad), bad).failure());
        }
    }

    @Test
    void aRealProducerExportBecomesAFormat1SnapshotTheRealReaderAccepts() throws Exception {
        byte[] export = resource("export-valid.json");
        JsonNode root = HandoffFixtures.parse(export);
        GraphHandoffRequest request = new GraphHandoffRequest(root.get("handoffId").stringValue(),
                Canonical.digest(root.get("manifest")), Canonical.sha256(Canonical.bytes(root.get("bundle"))), "operator-a");
        VerifiedHandoff verified = new HandoffExportParser().parse(export, request);
        HandoffBundle bundle = verified.bundle();
        // No catalog is consulted: the snapshot is a function of the verified bundle alone.
        String versionId = HandoffSnapshotWriter.versionId(bundle.handoffId());

        byte[] bytes = HandoffSnapshotWriter.snapshot(versionId, bundle);

        PublicGraphSnapshot snapshot = GraphSnapshotCodec.read(bytes, versionId);
        assertEquals(PublicGraphSnapshot.FORMAT, snapshot.snapshotFormat());
        assertEquals("handoff-1", snapshot.sourceBundleId());
        assertEquals(2, snapshot.companies().size());
        assertEquals(2, snapshot.issues().size());
        assertEquals(4, snapshot.relations().size());
        assertEquals(3, snapshot.articles().size());
        assertEquals(6, snapshot.evidence().size());
        assertEquals(List.of("FOLLOWS", "INVOLVES", "INVOLVES", "STRUCTURALLY_RELATED_TO"),
                snapshot.relations().stream().map(PublicGraphSnapshot.Relation::relationType).toList());
        // The article without any publication time stays null; the others are instants in UTC.
        assertEquals(1, snapshot.articles().stream().filter(a -> a.publishedAt() == null).count());
        assertTrue(snapshot.articles().stream().filter(a -> a.publishedAt() != null)
                .allMatch(a -> a.publishedAt().equals("2026-10-08T00:00:00Z")));
        // Unknown validity of the manual structural basis stays unknown (never a forever-valid window).
        var basis = snapshot.relations().stream().filter(r -> r.relationType().equals("STRUCTURALLY_RELATED_TO")).findFirst()
                .orElseThrow().basis().get(0);
        assertNull(basis.validFrom());
        assertNull(basis.validUntil());
        // The same bytes every time.
        assertEquals(new String(bytes, java.nio.charset.StandardCharsets.UTF_8),
                new String(HandoffSnapshotWriter.snapshot(versionId, bundle), java.nio.charset.StandardCharsets.UTF_8));
        // The retained receipt carries every producer field the snapshot does not (period, decisions, source references).
        JsonNode receipt = HandoffFixtures.parse(HandoffSnapshotWriter.receipt(verified));
        assertEquals(root.get("bundle"), receipt.get("bundle"));
        assertTrue(receipt.get("bundle").get("issues").get(0).has("period"));
        assertTrue(!new String(bytes, java.nio.charset.StandardCharsets.UTF_8).contains("period"));
    }

    private static byte[] resource(String name) throws IOException {
        try (InputStream in = HandoffSnapshotWriterTest.class.getClassLoader().getResourceAsStream("graph-handoff/" + name)) {
            return in.readAllBytes();
        }
    }
}
