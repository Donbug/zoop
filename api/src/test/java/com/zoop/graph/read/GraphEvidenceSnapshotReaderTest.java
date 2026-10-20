package com.zoop.graph.read;

import static com.zoop.graph.read.GraphReadFixtures.AI_ACCEL;
import static com.zoop.graph.read.GraphReadFixtures.HBM_SUPPLY;
import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertNotNull;
import static org.junit.jupiter.api.Assertions.assertNull;
import static org.junit.jupiter.api.Assertions.assertThrows;

import com.zoop.common.exception.CustomException;
import com.zoop.common.exception.ErrorCode;
import com.zoop.document.evidence.graph.GraphEvidence;
import com.zoop.graph.snapshot.PublicGraphSnapshot.Evidence;
import java.time.Instant;
import java.util.List;
import java.util.Set;
import org.junit.jupiter.api.Test;

class GraphEvidenceSnapshotReaderTest {
    private static final Instant NOW = Instant.parse("2026-10-16T12:00:00Z");
    private static final String ACTIVE = "fixture-2026-10-08";
    private static final String OLD = "fixture-2026-10-01";

    private static GraphEvidenceSnapshotReader reader(DisclosureExclusions exclusions) {
        return new GraphEvidenceSnapshotReader(GraphReadFixtures.reader(NOW, () -> exclusions));
    }

    private static Evidence evidenceOf(String articleId, int start) {
        return GraphReadFixtures.snapshot(ACTIVE).evidence().stream()
                .filter(e -> e.articleId().equals(articleId) && e.start() == start).findFirst().orElseThrow();
    }

    private static ErrorCode failure(Runnable action) {
        return assertThrows(CustomException.class, action::run).getErrorCode();
    }

    @Test
    void aVisibleEvidenceGivesItsSpanTheCitingVisibleIssuesAndTheSelectedVersion() {
        Evidence expected = evidenceOf("art-hbm-supply", 41);

        GraphEvidence found = reader(DisclosureExclusions.NONE).read(null, null, expected.evidenceId());

        assertEquals(ACTIVE, found.graphVersion());
        assertEquals(NOW, found.asOf(), "without an asOf the reported reference time is the request start");
        assertEquals(new GraphEvidence.Span("art-hbm-supply", "v1", 41, 90), found.span());
        assertEquals(List.of(HBM_SUPPLY), found.eventIds());
    }

    @Test
    void anIdThatTheVersionDoesNotListHasNoSpan() {
        GraphEvidence found = reader(DisclosureExclusions.NONE).read(null, null, "ev-" + "0".repeat(64));

        assertNull(found.span());
        assertEquals(List.of(), found.eventIds());
    }

    @Test
    void aPinnedOlderVersionHidesEvidenceItNeverContainedAndShowsTheRest() {
        Evidence added = evidenceOf("art-ai-accel", 0);
        Evidence old = evidenceOf("art-hbm-supply", 0);

        assertNull(reader(DisclosureExclusions.NONE).read(OLD, null, added.evidenceId()).span());
        GraphEvidence found = reader(DisclosureExclusions.NONE).read(OLD, null, old.evidenceId());
        assertEquals(OLD, found.graphVersion());
        assertNotNull(found.span());
        assertEquals(AI_ACCEL, reader(DisclosureExclusions.NONE).read(null, null, added.evidenceId()).eventIds().get(0));
    }

    @Test
    void asOfPinsTheThenActiveVersion() {
        Evidence added = evidenceOf("art-ai-accel", 0);
        Evidence later = evidenceOf("art-euv-export", 0);
        Instant early = Instant.parse("2026-10-02T00:00:00Z");

        GraphEvidence found = reader(DisclosureExclusions.NONE).read(null, early, later.evidenceId());
        assertEquals(OLD, found.graphVersion());
        assertEquals(early, found.asOf());
        assertNotNull(found.span());
        assertNull(reader(DisclosureExclusions.NONE).read(null, early, added.evidenceId()).span(),
                "the version active at that time never contained this evidence");
        GraphEvidence current = reader(DisclosureExclusions.NONE).read(null, Instant.parse("2026-10-09T00:00:00Z"), added.evidenceId());
        assertEquals(ACTIVE, current.graphVersion());
        assertNotNull(current.span());
    }

    @Test
    void anExcludedIssueOrEvidenceIsNotReadableEvenThoughTheEvidenceListIsOtherwiseUnchanged() {
        Evidence supply = evidenceOf("art-hbm-supply", 0);

        DisclosureExclusions issue = new DisclosureExclusions(1, Set.of(HBM_SUPPLY), Set.of(), Set.of());
        assertNull(reader(issue).read(null, null, supply.evidenceId()).span(), "no visible issue or relation cites it any more");

        DisclosureExclusions evidence = new DisclosureExclusions(1, Set.of(), Set.of(), Set.of(supply.evidenceId()));
        assertNull(reader(evidence).read(null, null, supply.evidenceId()).span());
        assertNull(reader(evidence).read(null, null, evidenceOf("art-hbm-supply", 41).evidenceId()).span(),
                "the issue's only geography evidence is excluded, so the whole issue is gone");
        assertNotNull(reader(evidence).read(null, null, evidenceOf("art-hbm-equip", 0).evidenceId()).span(), "another issue is unaffected");
    }

    @Test
    void selectionFailuresKeepTheirOwnStatus() {
        String id = evidenceOf("art-hbm-supply", 0).evidenceId();
        GraphEvidenceSnapshotReader reader = reader(DisclosureExclusions.NONE);

        assertEquals(ErrorCode.VERSION_UNAVAILABLE, failure(() -> reader.read("fixture-unknown", null, id)));
        assertEquals(ErrorCode.VERSION_UNAVAILABLE, failure(() -> reader.read(null, Instant.parse("2026-09-01T00:00:00Z"), id)));
        assertEquals(ErrorCode.INVALID_REQUEST, failure(() -> reader.read(ACTIVE, Instant.parse("2026-10-02T00:00:00Z"), id)),
                "a graphVersion that is not the one active at asOf");
    }
}
