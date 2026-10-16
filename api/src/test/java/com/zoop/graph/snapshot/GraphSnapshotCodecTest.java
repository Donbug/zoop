package com.zoop.graph.snapshot;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.junit.jupiter.api.Assertions.assertTrue;

import java.io.IOException;
import java.io.InputStream;
import java.nio.charset.StandardCharsets;
import org.junit.jupiter.api.Test;

class GraphSnapshotCodecTest {
    static byte[] fixture(String name) throws IOException {
        try (InputStream in = GraphSnapshotCodecTest.class.getClassLoader().getResourceAsStream("graph-fixtures/" + name)) {
            return in.readAllBytes();
        }
    }

    private static String v1() throws IOException {
        return new String(fixture("fixture-2026-10-01.json"), StandardCharsets.UTF_8);
    }

    private static String reason(String json, String versionId) {
        return assertThrows(GraphSnapshotUnavailableException.class,
                () -> GraphSnapshotCodec.read(json.getBytes(StandardCharsets.UTF_8), versionId)).reason();
    }

    @Test
    void bundledFixturesAreValidSnapshots() throws IOException {
        PublicGraphSnapshot v1 = GraphSnapshotCodec.read(fixture("fixture-2026-10-01.json"), "fixture-2026-10-01");
        PublicGraphSnapshot v2 = GraphSnapshotCodec.read(fixture("fixture-2026-10-08.json"), "fixture-2026-10-08");
        assertEquals(3, v1.issues().size());
        assertEquals(8, v1.relations().size());
        assertEquals(4, v2.issues().size());
        assertTrue(v1.relations().stream().anyMatch(r -> r.relationType().equals("FOLLOWS")));
    }

    @Test
    void versionIdMustMatchTheRegisteredVersion() throws IOException {
        assertEquals("snapshot_invalid:version_mismatch", reason(v1(), "fixture-2026-10-08"));
    }

    @Test
    void unknownKeysAreRejectedNotDropped() throws IOException {
        assertEquals("snapshot_malformed", reason(v1().replaceFirst("\\{", "{\"holding\": true,"), "fixture-2026-10-01"));
    }

    @Test
    void unresolvedGeographyIsRejected() throws IOException {
        assertEquals("snapshot_invalid:issue_geography",
                reason(v1().replace("\"geography\": \"domestic\"", "\"geography\": \"unknown\""), "fixture-2026-10-01"));
    }

    @Test
    void geographyWithoutSupportingEvidenceIsRejected() throws IOException {
        String json = v1().replaceFirst("\"geographyEvidenceIds\": \\[[^\\]]*\\]", "\"geographyEvidenceIds\": []");
        assertEquals("snapshot_invalid:issue_geography_evidence", reason(json, "fixture-2026-10-01"));
    }

    @Test
    void eventTimeMustKeepItsStatedPrecision() throws IOException {
        // A day value labelled as month precision is neither widened nor truncated.
        String json = v1().replace("\"eventTime\": \"2026-09\"", "\"eventTime\": \"2026-09-28\"");
        assertEquals("snapshot_invalid:issue_event_time", reason(json, "fixture-2026-10-01"));
    }

    @Test
    void unparsablePublicationTimeIsRejected() throws IOException {
        String json = v1().replace("\"publishedAt\": \"2026-09-25\"", "\"publishedAt\": \"2026-09-25 morning\"");
        assertEquals("snapshot_invalid:article_published_at", reason(json, "fixture-2026-10-01"));
    }

    @Test
    void unknownPublicationTimeIsKeptButAnOffsetLessTimeIsRejected() throws IOException {
        // The AI handoff sends publishedAt=null for an unknown time (contract §0); the snapshot keeps it as unknown.
        String json = v1().replace("\"publishedAt\": \"2026-09-25\"", "\"publishedAt\": null")
                .replace("\"latestPublishedAt\": \"2026-09-25\"", "\"latestPublishedAt\": null");
        PublicGraphSnapshot undated = GraphSnapshotCodec.read(json.getBytes(StandardCharsets.UTF_8), "fixture-2026-10-01");
        assertTrue(undated.articles().stream().anyMatch(a -> a.publishedAt() == null));
        // An offset-less time is not an instant: the AI side sends it as null, so a string here is malformed.
        String local = v1().replace("\"publishedAt\": \"2026-09-25\"", "\"publishedAt\": \"2026-09-25T09:30:00\"");
        assertEquals("snapshot_invalid:article_published_at", reason(local, "fixture-2026-10-01"));
    }

    @Test
    void precisionRulesCoverEveryOpenApiValue() {
        assertTrue(GraphSnapshotCodec.matchesPrecision("2026", "year"));
        assertTrue(GraphSnapshotCodec.matchesPrecision("2026-09", "month"));
        assertTrue(GraphSnapshotCodec.matchesPrecision("2026-09-22", "day"));
        assertTrue(GraphSnapshotCodec.matchesPrecision("2026-09-22T01:00:00Z", "datetime"));
        assertTrue(GraphSnapshotCodec.matchesPrecision(null, "unknown"));
        assertFalse(GraphSnapshotCodec.matchesPrecision("2026-09-22", "datetime"));
        assertFalse(GraphSnapshotCodec.matchesPrecision("2026", "unknown"));
        assertFalse(GraphSnapshotCodec.matchesPrecision(null, "day"));
    }

    @Test
    void internalAiRelationTypesAreNotPublicTypes() throws IOException {
        assertEquals("snapshot_invalid:relation_type",
                reason(v1().replaceFirst("\"relationType\": \"INVOLVES\"", "\"relationType\": \"SUPPLIES\""), "fixture-2026-10-01"));
    }

    @Test
    void relationToAnUnknownCompanyIsRejected() throws IOException {
        assertEquals("snapshot_invalid:relation_endpoint",
                reason(v1().replace("\"target\": \"NASDAQ:NVDA\"", "\"target\": \"NASDAQ:NOPE\""), "fixture-2026-10-01"));
    }

    @Test
    void approvedRelationNeedsEvidence() throws IOException {
        String json = v1().replaceFirst("(\"relationId\": \"rel-fixture-01\",[\\s\\S]*?\"evidenceIds\": )\\[[^\\]]*\\]", "$1[]");
        assertEquals("snapshot_invalid:relation_without_evidence", reason(json, "fixture-2026-10-01"));
    }

    @Test
    void structuralBasisKeepsItsPathAndMustCiteAPinnedArticle() throws IOException {
        var basis = GraphSnapshotCodec.read(v1().getBytes(StandardCharsets.UTF_8), "fixture-2026-10-01").relations().stream()
                .filter(r -> r.relationId().equals("rel-fixture-04")).findFirst().orElseThrow().basis().get(0);
        assertEquals("basis-fixture-04", basis.basisId());
        assertEquals("SUPPLIES", basis.relationType());
        assertEquals(java.util.List.of("KR"), basis.countries());
        assertEquals("art-hbm-equip", basis.articleId());

        String unpinned = v1().replaceFirst("(\"basisId\": \"basis-fixture-04\",[\\s\\S]*?\"articleVersion\": )\"v1\"", "$1\"v9\"");
        assertEquals("snapshot_invalid:relation_basis_article", reason(unpinned, "fixture-2026-10-01"));
        String half = v1().replaceFirst("(\"basisId\": \"basis-fixture-04\",[\\s\\S]*?\"articleVersion\": )\"v1\"", "$1null");
        assertEquals("snapshot_invalid:relation_basis_article", reason(half, "fixture-2026-10-01"));
    }

    @Test
    void emptyGraphIsAValidSnapshot() {
        String json = """
                {"snapshotFormat": 2, "versionId": "fixture-empty", "sourceBundleId": null, "companies": [],
                 "issues": [], "relations": [], "articles": [], "evidence": []}
                """;
        PublicGraphSnapshot snapshot = GraphSnapshotCodec.read(json.getBytes(StandardCharsets.UTF_8), "fixture-empty");
        assertTrue(snapshot.relations().isEmpty());
    }
}
