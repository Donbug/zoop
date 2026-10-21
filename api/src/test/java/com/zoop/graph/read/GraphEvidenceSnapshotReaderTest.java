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
import com.zoop.graph.snapshot.PublicGraphSnapshot;
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

    // ---- basis-only spans ---------------------------------------------------------------------------------------------------

    private static final String DIRECT = "ev-direct";
    private static final String GEO = "ev-geo";
    private static final String BASIS_ONLY = "ev-basis-only";
    private static final String OTHER_ARTICLE = "ev-other-article";
    private static final String RELATION = "rel-structural";
    private static final String BASIS_ID = "basis-1";
    /** The basis was verified after the 10-01 activation but before the 10-08 one, so an asOf between them can filter it. */
    private static final String VERIFIED = "2026-10-05T00:00:00Z";

    /** One issue citing {@link #DIRECT} and {@link #GEO}, one structural edge whose single basis rests on article {@code art-1}. */
    private static PublicGraphSnapshot basisSnapshot() {
        return new PublicGraphSnapshot(PublicGraphSnapshot.FORMAT, ACTIVE, "bundle-unit",
                List.of(new PublicGraphSnapshot.Company("KRX:A", "A", null, null), new PublicGraphSnapshot.Company("KRX:B", "B", null, null)),
                List.of(new PublicGraphSnapshot.Issue("iss-1", "이슈", "2026-09-01", "day", null, null, null, null, "domestic", "geo-1",
                        List.of(GEO), List.of("art-1"), List.of(DIRECT, GEO), List.of(), null, "2026-09-01")),
                List.of(new PublicGraphSnapshot.Relation("rel-involves", "INVOLVES", "iss-1", "KRX:A", null, null, List.of(DIRECT), List.of()),
                        new PublicGraphSnapshot.Relation(RELATION, "STRUCTURALLY_RELATED_TO", "iss-1", "KRX:B", null, null,
                                List.of(DIRECT), List.of(new PublicGraphSnapshot.Basis(BASIS_ID, "SUPPLIES", VERIFIED, null, null,
                                        List.of("KR"), List.of(new PublicGraphSnapshot.ArticleRef("art-1", "v1")))))),
                List.of(new PublicGraphSnapshot.Article("art-1", "v1", "제목", "https://example.invalid/1", "2026-09-01"),
                        new PublicGraphSnapshot.Article("art-2", "v1", "다른 제목", "https://example.invalid/2", "2026-09-01")),
                List.of(new Evidence(DIRECT, "art-1", "v1", 0, 5), new Evidence(GEO, "art-1", "v1", 6, 9),
                        new Evidence(BASIS_ONLY, "art-1", "v1", 10, 20), new Evidence(OTHER_ARTICLE, "art-2", "v1", 0, 3)));
    }

    private static GraphEvidenceSnapshotReader basisReader(DisclosureExclusions exclusions) {
        PublicGraphSnapshot snapshot = basisSnapshot();
        return new GraphEvidenceSnapshotReader(new PublicGraphReader(
                new com.zoop.graph.version.GraphVersionSelector(GraphReadFixtures.repository(),
                        java.time.Clock.fixed(NOW, java.time.ZoneOffset.UTC)),
                version -> snapshot, () -> exclusions));
    }

    @Test
    void aSpanNoVisibleIssueOrRelationCitesButAVisibleBasisReferencesIsBasisOnlyWithoutEventIds() {
        GraphEvidence found = basisReader(DisclosureExclusions.NONE).read(null, null, BASIS_ONLY);

        assertEquals(new GraphEvidence.Span("art-1", "v1", 10, 20), found.span());
        assertEquals(List.of(), found.eventIds(), "a basis is not an event");
        assertEquals(List.of(new GraphEvidence.BasisRef(RELATION, "STRUCTURALLY_RELATED_TO", "iss-1", "KRX:B", BASIS_ID)),
                found.basisRefs());
    }

    @Test
    void aDirectlyCitedSpanKeepsItsEventsAndNeedsNoBasisProof() {
        GraphEvidence found = basisReader(DisclosureExclusions.NONE).read(null, null, DIRECT);

        assertEquals(List.of("iss-1"), found.eventIds());
        assertEquals(List.of(), found.basisRefs());
        assertEquals(List.of("iss-1"), basisReader(DisclosureExclusions.NONE).read(null, null, GEO).eventIds());
    }

    @Test
    void aSpanOfAnArticleNoBasisReferencesIsNotVisibleAtAll() {
        GraphEvidence found = basisReader(DisclosureExclusions.NONE).read(null, null, OTHER_ARTICLE);

        assertNull(found.span());
        assertEquals(List.of(), found.basisRefs());
    }

    @Test
    void aBasisThatAsOfHasNotYetVerifiedNeverMakesItsSpanVisible() {
        Instant before = Instant.parse("2026-10-03T00:00:00Z");
        Instant after = Instant.parse("2026-10-06T00:00:00Z");

        GraphEvidence early = basisReader(DisclosureExclusions.NONE).read(null, before, BASIS_ONLY);
        assertNull(early.span(), "the basis was verified after asOf, so its relation and its evidence are not yet public");
        assertEquals(List.of(), early.basisRefs());
        assertEquals(List.of("iss-1"), basisReader(DisclosureExclusions.NONE).read(null, before, DIRECT).eventIds(),
                "directly cited evidence is unaffected by the basis time");

        GraphEvidence verified = basisReader(DisclosureExclusions.NONE).read(null, after, BASIS_ONLY);
        assertNotNull(verified.span());
        assertEquals(1, verified.basisRefs().size());
    }

    @Test
    void anExcludedRelationIssueOrEvidenceWithdrawsTheBasisOnlySpan() {
        assertNull(basisReader(new DisclosureExclusions(1, Set.of(), Set.of(RELATION), Set.of())).read(null, null, BASIS_ONLY).span(),
                "the structural relation is excluded");
        assertNull(basisReader(new DisclosureExclusions(1, Set.of("iss-1"), Set.of(), Set.of())).read(null, null, BASIS_ONLY).span(),
                "the issue is excluded, so its relations go with it");
        assertNull(basisReader(new DisclosureExclusions(1, Set.of(), Set.of(), Set.of(BASIS_ONLY))).read(null, null, BASIS_ONLY).span(),
                "the evidence itself is excluded");
        assertNotNull(basisReader(new DisclosureExclusions(1, Set.of(), Set.of("rel-involves"), Set.of())).read(null, null, BASIS_ONLY).span(),
                "an unrelated relation exclusion changes nothing");
    }
}
