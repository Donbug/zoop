package com.zoop.graph.read;

import static com.zoop.graph.read.GraphReadFixtures.AI_ACCEL;
import static com.zoop.graph.read.GraphReadFixtures.HBM_EQUIP;
import static com.zoop.graph.read.GraphReadFixtures.HBM_SUPPLY;
import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertTrue;

import com.zoop.graph.snapshot.GraphSnapshotCodec;
import com.zoop.graph.snapshot.PublicGraphSnapshot;
import com.zoop.graph.snapshot.PublicGraphSnapshot.Issue;
import com.zoop.graph.snapshot.PublicGraphSnapshot.Relation;
import java.nio.charset.StandardCharsets;
import java.time.Instant;
import java.util.List;
import java.util.Set;
import org.junit.jupiter.api.Test;

class GraphSnapshotFilterTest {
    private final PublicGraphSnapshot v2 = GraphReadFixtures.snapshot("fixture-2026-10-08");

    private static Set<String> issueIds(PublicGraphSnapshot s) {
        return s.issues().stream().map(Issue::issueId).collect(java.util.stream.Collectors.toSet());
    }

    @Test
    void dateOnlyPublicationCountsOnlyAfterThatDayEndedEverywhere() {
        // Article dated 2026-09-25 (no time): counts only once asOf's date at UTC-12 is after it; the same day never counts.
        assertFalse(GraphSnapshotFilter.publishedBy("2026-09-25", Instant.parse("2026-09-25T23:00:00Z")));
        assertFalse(GraphSnapshotFilter.publishedBy("2026-09-25", Instant.parse("2026-09-26T11:59:59Z")));
        assertTrue(GraphSnapshotFilter.publishedBy("2026-09-25", Instant.parse("2026-09-26T12:00:00Z")));
        // The contract example: asOf 2026-10-02T09:00+09:00 is 2026-10-01 at UTC-12.
        Instant kstMorning = Instant.parse("2026-10-02T00:00:00Z");
        assertTrue(GraphSnapshotFilter.publishedBy("2026-09-30", kstMorning));
        assertFalse(GraphSnapshotFilter.publishedBy("2026-10-01", kstMorning));
        assertTrue(GraphSnapshotFilter.publishedBy("2026-09-22T01:00:00Z", Instant.parse("2026-09-22T01:00:00Z")));
    }

    @Test
    void structuralBasisIsVisibleOnceVerifiedWhateverItsValidityDates() {
        Instant asOf = Instant.parse("2026-10-05T00:00:00Z");
        assertTrue(GraphSnapshotFilter.verifiedBy(basis("2026-09-29T00:00:00Z", "2026-09-01", null), asOf));
        assertFalse(GraphSnapshotFilter.verifiedBy(basis("2026-10-06T00:00:00Z", "2026-09-01", null), asOf));

        // FS042: a business relation not started yet (validFrom later) or already ended (validUntil earlier) is still
        // shown at asOf; its status, not its visibility, tells them apart.
        for (var dates : List.of(List.of("2026-11-01", ""), List.of("2026-01-01", "2026-03-31"))) {
            var shifted = new PublicGraphSnapshot(v2.snapshotFormat(), v2.versionId(), v2.sourceBundleId(), v2.companies(),
                    v2.issues(), v2.relations().stream().map(r -> r.basis().isEmpty() ? r : new Relation(r.relationId(),
                            r.relationType(), r.source(), r.target(), r.role(), r.assertionStatus(), r.evidenceIds(),
                            r.basis().stream().map(x -> new PublicGraphSnapshot.Basis(x.basisId(), x.relationType(),
                                    x.verifiedAt(), dates.get(0), dates.get(1).isEmpty() ? null : dates.get(1),
                                    x.countries(), x.articleId(), x.articleVersion())).toList())).toList(),
                    v2.articles(), v2.evidence());
            var visible = GraphSnapshotFilter.apply(shifted, Instant.parse("2026-10-12T00:00:00Z"), DisclosureExclusions.NONE);
            assertTrue(visible.relations().stream().anyMatch(r -> r.relationId().equals("rel-fixture-04")), dates.toString());
        }
    }

    private static PublicGraphSnapshot.Basis basis(String verifiedAt, String validFrom, String validUntil) {
        return new PublicGraphSnapshot.Basis("b", "SUPPLIES", verifiedAt, validFrom, validUntil, List.of(), null, null);
    }

    @Test
    void asOfKeepsOnlyWhatWasPublishedInsideThePinnedVersion() {
        PublicGraphSnapshot early = GraphSnapshotFilter.apply(v2, Instant.parse("2026-10-01T00:00:00Z"), DisclosureExclusions.NONE);
        assertFalse(issueIds(early).contains(AI_ACCEL));
        assertTrue(issueIds(early).contains(HBM_SUPPLY));
        assertTrue(early.relations().stream().noneMatch(r -> r.source().equals(AI_ACCEL)));
        assertEquals(4, issueIds(GraphSnapshotFilter.apply(v2, null, DisclosureExclusions.NONE)).size());
    }

    @Test
    void currentExclusionsApplyWithOrWithoutAsOf() {
        var excluded = new DisclosureExclusions(3, Set.of(HBM_EQUIP), Set.of(), Set.of());
        assertFalse(issueIds(GraphSnapshotFilter.apply(v2, null, excluded)).contains(HBM_EQUIP));
        assertFalse(issueIds(GraphSnapshotFilter.apply(v2, Instant.parse("2026-10-01T00:00:00Z"), excluded)).contains(HBM_EQUIP));
        // The FOLLOWS edge to the excluded issue disappears with it.
        assertTrue(GraphSnapshotFilter.apply(v2, null, excluded).relations().stream()
                .noneMatch(r -> r.source().equals(HBM_EQUIP) || r.target().equals(HBM_EQUIP)));
    }

    @Test
    void withdrawnEvidenceRemovesTheRelationItSupports() {
        String evidenceOfRel01 = v2.relations().stream().filter(r -> r.relationId().equals("rel-fixture-01"))
                .findFirst().orElseThrow().evidenceIds().get(0);
        var excluded = new DisclosureExclusions(4, Set.of(), Set.of(), Set.of(evidenceOfRel01));
        PublicGraphSnapshot visible = GraphSnapshotFilter.apply(v2, null, excluded);
        assertTrue(visible.relations().stream().noneMatch(r -> r.relationId().equals("rel-fixture-01")));
        assertTrue(visible.evidence().stream().noneMatch(e -> e.evidenceId().equals(evidenceOfRel01)));
    }

    @Test
    void withdrawnEvidenceRemovesAFollowsEdgeThatCitesIt() {
        // rel-fixture-04's evidence is not geography evidence, so withdrawing it leaves both endpoint issues in place.
        String evidenceId = v2.relations().stream().filter(r -> r.relationId().equals("rel-fixture-04"))
                .findFirst().orElseThrow().evidenceIds().get(0);
        // Same snapshot, but the FOLLOWS edge carries its own evidence ID.
        PublicGraphSnapshot cited = new PublicGraphSnapshot(v2.snapshotFormat(), v2.versionId(), v2.sourceBundleId(),
                v2.companies(), v2.issues(), v2.relations().stream().map(r -> "FOLLOWS".equals(r.relationType())
                        ? new Relation(r.relationId(), r.relationType(), r.source(), r.target(), r.role(),
                                r.assertionStatus(), List.of(evidenceId), r.basis())
                        : r).toList(), v2.articles(), v2.evidence());
        var excluded = new DisclosureExclusions(5, Set.of(), Set.of(), Set.of(evidenceId));

        assertTrue(hasFollows(GraphSnapshotFilter.apply(cited, null, DisclosureExclusions.NONE)));
        PublicGraphSnapshot visible = GraphSnapshotFilter.apply(cited, null, excluded);
        assertFalse(hasFollows(visible));
        // The edge goes because of its evidence, not because an endpoint issue went.
        assertTrue(issueIds(visible).containsAll(Set.of(HBM_EQUIP, HBM_SUPPLY)));
        // A FOLLOWS edge without evidence IDs is still kept.
        assertTrue(hasFollows(GraphSnapshotFilter.apply(v2, null, excluded)));
    }

    @Test
    void undatedArticleShowsInTheCurrentGraphButNeverBeforeAnAsOf() {
        // The AI handoff may send publishedAt=null (unknown); its issue then has no known publication time either.
        String json = new String(GraphReadFixtures.bytes("fixture-2026-10-08"), StandardCharsets.UTF_8)
                .replace("\"publishedAt\": \"2026-09-25\"", "\"publishedAt\": null")
                .replace("\"latestPublishedAt\": \"2026-09-25\"", "\"latestPublishedAt\": null");
        PublicGraphSnapshot undated = GraphSnapshotCodec.read(json.getBytes(StandardCharsets.UTF_8), "fixture-2026-10-08");

        PublicGraphSnapshot current = GraphSnapshotFilter.apply(undated, null, DisclosureExclusions.NONE);
        assertTrue(issueIds(current).contains(HBM_EQUIP));
        assertTrue(current.articles().stream().anyMatch(a -> a.publishedAt() == null));
        // Even an asOf long after every dated article leaves the undated one, and the issue resting on it, out.
        PublicGraphSnapshot later = GraphSnapshotFilter.apply(undated, Instant.parse("2027-01-01T00:00:00Z"), DisclosureExclusions.NONE);
        assertFalse(issueIds(later).contains(HBM_EQUIP));
        assertTrue(later.articles().stream().noneMatch(a -> a.publishedAt() == null));
        assertTrue(issueIds(later).contains(HBM_SUPPLY));
        assertFalse(GraphSnapshotFilter.publishedBy(null, Instant.parse("2027-01-01T00:00:00Z")));
    }

    private static boolean hasFollows(PublicGraphSnapshot s) {
        return s.relations().stream().anyMatch(r -> "FOLLOWS".equals(r.relationType()));
    }
}
