package com.zoop.graph.read;

import static com.zoop.graph.read.GraphReadFixtures.AI_ACCEL;
import static com.zoop.graph.read.GraphReadFixtures.HBM_EQUIP;
import static com.zoop.graph.read.GraphReadFixtures.HBM_SUPPLY;
import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertTrue;

import com.zoop.graph.snapshot.PublicGraphSnapshot;
import com.zoop.graph.snapshot.PublicGraphSnapshot.Issue;
import com.zoop.graph.snapshot.PublicGraphSnapshot.Relation;
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
        // Article dated 2026-09-25 (no time): not provably published until 2026-09-26T12:00Z (end of the day at UTC-12).
        assertFalse(GraphSnapshotFilter.publishedBy("2026-09-25", Instant.parse("2026-09-26T11:59:59Z")));
        assertTrue(GraphSnapshotFilter.publishedBy("2026-09-25", Instant.parse("2026-09-26T12:00:00Z")));
        assertTrue(GraphSnapshotFilter.publishedBy("2026-09-22T01:00:00Z", Instant.parse("2026-09-22T01:00:00Z")));
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

    private static boolean hasFollows(PublicGraphSnapshot s) {
        return s.relations().stream().anyMatch(r -> "FOLLOWS".equals(r.relationType()));
    }
}
