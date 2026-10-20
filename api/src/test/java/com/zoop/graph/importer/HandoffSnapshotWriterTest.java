package com.zoop.graph.importer;

import java.io.IOException;
import java.io.InputStream;
import java.nio.charset.StandardCharsets;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.Comparator;
import java.util.List;

import com.zoop.common.json.Canonical;
import com.zoop.graph.importer.HandoffBundle.Article;
import com.zoop.graph.importer.HandoffBundle.Evidence;
import com.zoop.graph.importer.HandoffBundle.Issue;
import com.zoop.graph.importer.HandoffBundle.ObservationPin;
import com.zoop.graph.importer.HandoffExportParser.VerifiedHandoff;
import com.zoop.graph.snapshot.GraphSnapshotCodec;
import com.zoop.graph.snapshot.PublicGraphSnapshot;
import com.zoop.graph.snapshot.PublicGraphSnapshot.ArticleRef;
import com.zoop.graph.snapshot.PublicGraphSnapshot.MentionRef;
import org.junit.jupiter.api.Test;
import tools.jackson.databind.JsonNode;
import tools.jackson.databind.node.ArrayNode;
import tools.jackson.databind.node.ObjectNode;

import static org.junit.jupiter.api.Assertions.assertArrayEquals;
import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertNotEquals;
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
    void aRealProducerExportBecomesAFormat3SnapshotTheRealReaderAccepts() throws Exception {
        byte[] export = resource("export-valid.json");
        JsonNode root = HandoffFixtures.parse(export);
        VerifiedHandoff verified = verifiedResource(export, root);
        HandoffBundle bundle = verified.bundle();
        // No catalog is consulted: the snapshot is a function of the verified bundle alone.
        String versionId = HandoffSnapshotWriter.versionId(bundle.handoffId());

        byte[] bytes = HandoffSnapshotWriter.snapshot(versionId, verified);

        PublicGraphSnapshot snapshot = GraphSnapshotCodec.read(bytes, versionId);
        assertEquals(3, snapshot.snapshotFormat());
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

        // Issue period, issue-level assertion status, mention references and the representative come from the producer's issue.
        PublicGraphSnapshot.Issue supply = issue(snapshot, "issue:supply-2026q3");
        assertEquals("2026Q3", supply.period());
        assertEquals("announced", supply.assertionStatus());
        // The S2 comparison and the S2 snapshot both list mention m-a of document a: one mention. Mention ids are the app's own.
        assertEquals(ascending(ref(A_ID, A_VERSION, "m-a"), ref(A2_ID, A2_VERSION, "m-a2")), supply.mentions());
        assertEquals(appMention(A_ID, A_VERSION, "m-a"), supply.representativeMentionId());
        PublicGraphSnapshot.Issue factory = issue(snapshot, "issue:factory-2026q4");
        assertEquals("2026Q4", factory.period());
        assertEquals(List.of(ref(B_ID, B_VERSION, "m-b")), factory.mentions());
        assertNull(factory.representativeMentionId());

        // The structural basis is structured: its own id, the business relation type, countries and every source article.
        var basis = snapshot.relations().stream().filter(r -> r.relationType().equals("STRUCTURALLY_RELATED_TO")).findFirst()
                .orElseThrow().basis().get(0);
        assertEquals("074949b69d25fefaa5c75af0a78de7015a773f58e91003a37cebd878d116f743", basis.basisId());
        assertEquals("SUPPLIES", basis.relationType());
        assertEquals(List.of(), basis.countries());
        assertEquals(List.of(new ArticleRef(A_ID, A_VERSION)), basis.articles());
        // Unknown validity of the manual structural basis stays unknown (never a forever-valid window).
        assertNull(basis.validFrom());
        assertNull(basis.validUntil());
        // The same bytes every time.
        assertArrayEquals(bytes, HandoffSnapshotWriter.snapshot(versionId, verified));
        // The retained receipt carries the complete original bundle, with the producer's own mention ids.
        JsonNode receipt = HandoffFixtures.parse(HandoffSnapshotWriter.receipt(verified));
        assertEquals(root.get("bundle"), receipt.get("bundle"));
        assertEquals(3, receipt.get("bundle").get("issues").get(1).get("sourceEvents").size());
        // Three source events of two document versions are two original mentions (the comparison and the snapshot list m-a of document a).
        assertEquals(2, receipt.get("bundle").get("issues").get(1).get("mentions").size());
        assertTrue(receipt.get("bundle").get("issues").get(0).has("period"));
    }

    @Test
    void aRealProducerCollisionOfALocalMentionIdKeepsBothMentionsAndTheRightRepresentative() throws Exception {
        byte[] export = resource("export-collision.json");
        JsonNode root = HandoffFixtures.parse(export);
        VerifiedHandoff verified = verifiedResource(export, root);
        String versionId = version(verified);

        byte[] bytes = HandoffSnapshotWriter.snapshot(versionId, verified);

        // Documents a and a2 of ONE issue both use the producer-local mention id m-a (S2 scopes it by document version): legal input.
        PublicGraphSnapshot snapshot = GraphSnapshotCodec.read(bytes, versionId);
        PublicGraphSnapshot.Issue supply = issue(snapshot, "issue:supply-2026q3");
        assertEquals(ascending(ref(A_ID, A_VERSION, "m-a"), ref(A2_ID, A2_VERSION, "m-a")), supply.mentions());
        assertEquals(2, supply.mentions().stream().map(MentionRef::mentionId).distinct().count());
        assertTrue(supply.mentions().stream().noneMatch(m -> m.mentionId().equals("m-a")));
        // The representative is the member of document a, never the other document's m-a.
        assertEquals(appMention(A_ID, A_VERSION, "m-a"), supply.representativeMentionId());
        assertNotEquals(appMention(A2_ID, A2_VERSION, "m-a"), supply.representativeMentionId());
        // Nothing else was dropped to make the ids unique.
        assertEquals(2, snapshot.issues().size());
        assertEquals(4, snapshot.relations().size());
        assertEquals(3, snapshot.articles().size());
        assertEquals(6, snapshot.evidence().size());
        assertEquals(List.of(ref(B_ID, B_VERSION, "m-b")), issue(snapshot, "issue:factory-2026q4").mentions());
        // A retry reproduces the same ids and the same bytes, also from a freshly verified copy of the same export.
        assertArrayEquals(bytes, HandoffSnapshotWriter.snapshot(versionId, verifiedResource(export, root)));
        // The producer's local ids stay in the retained receipt: all three source events of the issue still say m-a.
        JsonNode receipt = HandoffFixtures.parse(HandoffSnapshotWriter.receipt(verified));
        assertEquals(root.get("bundle"), receipt.get("bundle"));
        JsonNode events = receipt.get("bundle").get("issues").get(1).get("sourceEvents");
        assertEquals(3, events.size());
        assertTrue(events.values().stream().allMatch(event -> event.get("mentionId").stringValue().equals("m-a")));
        // ... and the two documents stay two original mentions with one local id, never merged and never renamed in the receipt.
        JsonNode mentions = receipt.get("bundle").get("issues").get(1).get("mentions");
        assertEquals(2, mentions.size());
        assertTrue(mentions.values().stream().allMatch(mention -> mention.get("mentionId").stringValue().equals("m-a")));
        assertEquals(2, mentions.values().stream().map(mention -> mention.get("documentId").stringValue()).distinct().count());
    }

    @Test
    void theValidityWindowKeepsItsLastValidDayAndEveryBasisFactAsGiven() {
        VerifiedHandoff verified = verified(HandoffFixtures.build());

        PublicGraphSnapshot snapshot = GraphSnapshotCodec.read(HandoffSnapshotWriter.snapshot(version(verified), verified),
                version(verified));

        var basis = snapshot.relations().stream().filter(r -> r.relationType().equals("STRUCTURALLY_RELATED_TO")).findFirst()
                .orElseThrow().basis().get(0);
        assertEquals("7".repeat(64), basis.basisId());
        assertEquals("SUPPLIES", basis.relationType());
        assertEquals(List.of("KR"), basis.countries());
        assertEquals(List.of(new ArticleRef(HandoffFixtures.ARTICLE_ID, HandoffFixtures.ARTICLE_VERSION)), basis.articles());
        assertEquals("2026-10-16T12:00:00.123456Z", basis.verifiedAt());
        assertEquals("2026-01-01", basis.validFrom());
        // The source states its last valid day: written as that day, with no midnight and no extra day.
        assertEquals("2026-12-31", basis.validUntil());
        PublicGraphSnapshot.Issue issue = snapshot.issues().get(0);
        assertEquals("2026Q3", issue.period());
        assertEquals("announced", issue.assertionStatus());
        assertEquals(List.of(ref(HandoffFixtures.ARTICLE_ID, HandoffFixtures.ARTICLE_VERSION, "m-1")), issue.mentions());
        assertNull(issue.representativeMentionId());
    }

    @Test
    void everyEventOfOneMentionIsOneMentionAndANamedRepresentativeIsWritten() {
        VerifiedHandoff verified = withEvents(false, "m-1", HandoffFixtures.ARTICLE_ID, HandoffFixtures.ARTICLE_VERSION, 0, true);

        PublicGraphSnapshot.Issue issue = written(verified).issues().get(0);

        assertEquals(List.of(ref(HandoffFixtures.ARTICLE_ID, HandoffFixtures.ARTICLE_VERSION, "m-1")), issue.mentions());
        assertEquals(appMention(HandoffFixtures.ARTICLE_ID, HandoffFixtures.ARTICLE_VERSION, "m-1"), issue.representativeMentionId());
    }

    @Test
    void mentionsOfTheIssuesOwnArticlesAreWrittenAscendingAndOthersStayInTheReceipt() {
        // Article B is cited by the issue's evidence: its mention is written beside the first one.
        VerifiedHandoff cited = withEvents(true, "m-0", SECOND_ARTICLE, SECOND_VERSION, 1, true);
        PublicGraphSnapshot.Issue issue = written(cited).issues().get(0);
        assertEquals(ascending(ref(SECOND_ARTICLE, SECOND_VERSION, "m-0"),
                ref(HandoffFixtures.ARTICLE_ID, HandoffFixtures.ARTICLE_VERSION, "m-1")), issue.mentions());
        assertEquals(appMention(SECOND_ARTICLE, SECOND_VERSION, "m-0"), issue.representativeMentionId());

        // Article B is in the bundle but no evidence of this issue cites it: the event is NOT a snapshot mention (it stays in the
        // receipt only), and a representative that is that event is written as none rather than as a mention the snapshot lacks.
        VerifiedHandoff uncited = withEvents(false, "m-0", SECOND_ARTICLE, SECOND_VERSION, 1, true);
        PublicGraphSnapshot.Issue partial = written(uncited).issues().get(0);
        assertEquals(List.of(ref(HandoffFixtures.ARTICLE_ID, HandoffFixtures.ARTICLE_VERSION, "m-1")), partial.mentions());
        assertNull(partial.representativeMentionId());
        JsonNode receipt = HandoffFixtures.parse(HandoffSnapshotWriter.receipt(uncited));
        assertEquals(2, receipt.get("bundle").get("issues").get(0).get("sourceEvents").size());
    }

    @Test
    void oneLocalMentionIdOnTwoArticleVersionsOfAnIssueKeepsBothUnderDistinctAppIdsAndTheRightRepresentative() {
        String first = HandoffFixtures.ARTICLE_ID;
        String firstVersion = HandoffFixtures.ARTICLE_VERSION;

        // The representative is the event of the second article.
        VerifiedHandoff ofTheSecond = withEvents(true, "m-1", SECOND_ARTICLE, SECOND_VERSION, 1, true);
        PublicGraphSnapshot.Issue second = written(ofTheSecond).issues().get(0);
        assertEquals(ascending(ref(first, firstVersion, "m-1"), ref(SECOND_ARTICLE, SECOND_VERSION, "m-1")), second.mentions());
        assertEquals(2, second.mentions().stream().map(MentionRef::mentionId).distinct().count());
        assertEquals(appMention(SECOND_ARTICLE, SECOND_VERSION, "m-1"), second.representativeMentionId());

        // The representative is the event of the first article: the same local id resolves to the first article's mention.
        VerifiedHandoff ofTheFirst = withEvents(true, "m-1", SECOND_ARTICLE, SECOND_VERSION, 1, false);
        ObjectNode rawIssue = (ObjectNode) ofTheFirst.bundleNode().get("issues").get(0);
        rawIssue.set("representative", rawIssue.get("sourceEvents").get(0).deepCopy());
        PublicGraphSnapshot.Issue firstIssue = written(ofTheFirst).issues().get(0);
        assertEquals(second.mentions(), firstIssue.mentions());
        assertEquals(appMention(first, firstVersion, "m-1"), firstIssue.representativeMentionId());
    }

    @Test
    void aDocumentIdentityThatMatchesTwoBundleArticlesIsRefusedNotGuessed() {
        VerifiedHandoff verified = verified(HandoffFixtures.build());
        HandoffBundle bundle = verified.bundle();
        Article first = bundle.articles().get(0);
        List<Article> articles = new ArrayList<>(bundle.articles());
        articles.add(new Article("doc-" + "9".repeat(64), "8".repeat(64), first.documentId(), first.documentVersion(),
                first.rawVersion(), first.title(), first.url(), first.publishedAt(), first.precision(), first.observations()));
        VerifiedHandoff ambiguous = new VerifiedHandoff(rebuilt(bundle, bundle.issues(), bundle.evidence(), articles),
                verified.manifest(), verified.manifestNode(), verified.bundleNode(), verified.receiptNode(),
                verified.attemptsNode(), verified.manifestDigest(), verified.bundleDigest(), verified.contentDigest());

        GraphHandoffException refused = assertThrows(GraphHandoffException.class,
                () -> HandoffSnapshotWriter.snapshot(version(ambiguous), ambiguous));

        assertEquals(GraphHandoffFailure.MENTION_ARTICLE_AMBIGUOUS, refused.failure());
    }

    // -------------------------------------------------------------------------------------------------- test builders ----

    private static final String SECOND_ARTICLE = "doc-" + "9".repeat(64);
    private static final String SECOND_VERSION = "8".repeat(64);
    private static final String SECOND_RAW = "7".repeat(64);
    // Documents a, a2 and b of the real producer exports under graph-handoff/ (content-derived, equal in every export).
    private static final String A_ID = "doc-5cf551c4a3ea4c5a0e6fcde416d2153d1b796251bb2e0b50bb20e1eb61dac458";
    private static final String A_VERSION = "e4cf9d2db4be08fc7c2c4e0a2d31ae042c61bb83e046f5a9283b43be0140307d";
    private static final String A2_ID = "doc-15e86e5ab95b2d8b7765a38ccf84d3c85aea3909f784f025770a714b01bbd1b7";
    private static final String A2_VERSION = "ada790eabf095b9e6430e6f0622e7614ecb14c600346b869db6fa2a695157903";
    private static final String B_ID = "doc-597676263c5323120431cc5d14b03ee798b62c9afc6375e71fb5a72ac81b9afa";
    private static final String B_VERSION = "6cbe480a580c19e69fbef46abf68a7b53e059a62e86813adffee98fc87313634";

    /**
     * The app's mention id, written out by hand and never taken from the writer: {@code "mention-"} + the SHA-256 of the canonical
     * JSON (sorted ASCII keys, no spaces) of the resolved article id and version and the producer's local mention id.
     */
    private static String appMention(String articleId, String articleVersion, String sourceMentionId) {
        String canonical = "{\"articleId\":\"" + articleId + "\",\"articleVersion\":\"" + articleVersion
                + "\",\"sourceMentionId\":\"" + sourceMentionId + "\"}";
        return "mention-" + Canonical.sha256(canonical.getBytes(StandardCharsets.UTF_8));
    }

    private static MentionRef ref(String articleId, String articleVersion, String sourceMentionId) {
        return new MentionRef(appMention(articleId, articleVersion, sourceMentionId), articleId, articleVersion);
    }

    /** The snapshot's order of mention references: ascending by app mention id. */
    private static List<MentionRef> ascending(MentionRef... refs) {
        return Arrays.stream(refs).sorted(Comparator.comparing(MentionRef::mentionId)).toList();
    }

    private static PublicGraphSnapshot.Issue issue(PublicGraphSnapshot snapshot, String issueId) {
        return snapshot.issues().stream().filter(i -> i.issueId().equals(issueId)).findFirst().orElseThrow();
    }

    private static VerifiedHandoff verifiedResource(byte[] export, JsonNode root) {
        GraphHandoffRequest request = new GraphHandoffRequest(root.get("handoffId").stringValue(),
                Canonical.digest(root.get("manifest")), Canonical.sha256(Canonical.bytes(root.get("bundle"))), "operator-a");
        return new HandoffExportParser().parse(export, request);
    }

    private static VerifiedHandoff verified(HandoffFixtures.Built built) {
        return new HandoffExportParser().parse(built.envelopeBytes(), built.request());
    }

    private static String version(VerifiedHandoff verified) {
        return HandoffSnapshotWriter.versionId(verified.bundle().handoffId());
    }

    /** The snapshot the real reader accepts for a verified handoff. */
    private static PublicGraphSnapshot written(VerifiedHandoff verified) {
        return GraphSnapshotCodec.read(HandoffSnapshotWriter.snapshot(version(verified), verified), version(verified));
    }

    private static HandoffBundle rebuilt(HandoffBundle bundle, List<Issue> issues, List<Evidence> evidence, List<Article> articles) {
        return new HandoffBundle(bundle.handoffId(), bundle.manifestDigest(), bundle.sourceKind(), bundle.executionMode(),
                bundle.recordingKind(), bundle.policyVersion(), bundle.files(), bundle.sources(), bundle.companies(), issues,
                bundle.relations(), evidence, articles);
    }

    /**
     * The standard handoff plus one more source event of the only issue: {@code mentionId} on the given article version. When
     * {@code citedByIssue}, that second article (B) is also a bundle article cited by one more evidence span of the issue; otherwise
     * B is only in the bundle. The event may be the issue's representative. Writer inputs only: the typed bundle and the raw bundle
     * node are kept consistent for exactly the fields the writer reads (the strict verifier is not re-run on this variant).
     */
    private static VerifiedHandoff withEvents(boolean citedByIssue, String mentionId, String articleId, String articleVersion,
            int ordinal, boolean representative) {
        VerifiedHandoff base = verified(HandoffFixtures.build());
        HandoffBundle typed = base.bundle();
        ObjectNode raw = ((ObjectNode) base.bundleNode()).deepCopy();
        List<Article> articles = new ArrayList<>(typed.articles());
        List<Evidence> evidence = new ArrayList<>(typed.evidence());
        List<Issue> issues = new ArrayList<>(typed.issues());
        boolean second = articleId.equals(SECOND_ARTICLE);
        if (second) {
            articles.add(new Article(SECOND_ARTICLE, SECOND_VERSION, SECOND_ARTICLE, SECOND_VERSION, SECOND_RAW, "합성 제목 B",
                    "https://example.invalid/b", null, "unknown", List.of(new ObservationPin(HandoffFixtures.SELECTOR.roundId(),
                            HandoffFixtures.SOURCE, 0, ordinal, HandoffFixtures.OBSERVED_AT, "operator-grant", "rights-1"))));
            if (citedByIssue) {
                String evidenceId = HandoffBundleVerifier.appEvidenceId(SECOND_ARTICLE, SECOND_VERSION, 0, 3);
                evidence.add(new Evidence(evidenceId, SECOND_ARTICLE, SECOND_VERSION, 0, 3, "a".repeat(64), List.of("loc-1"),
                        SECOND_ARTICLE, SECOND_VERSION, SECOND_RAW, "text-" + SECOND_VERSION, "ev-" + "1".repeat(32)));
                Issue issue = issues.get(0);
                List<String> evidenceIds = new ArrayList<>(issue.evidenceIds());
                evidenceIds.add(evidenceId);
                issues.set(0, new Issue(issue.id(), issue.title(), issue.action(), issue.target(), issue.eventTime(),
                        issue.timePrecision(), issue.assertionStatus(), issue.geography(), issue.geographyPolicyVersion(),
                        issue.geographyEvidenceIds(), evidenceIds));
            }
        }
        ObjectNode rawIssue = (ObjectNode) raw.get("issues").get(0);
        ArrayNode events = (ArrayNode) rawIssue.get("sourceEvents");
        ObjectNode event = ((ObjectNode) events.get(0)).deepCopy();
        event.put("kind", "snapshot-event");
        event.put("ref", "event-2");
        event.put("mentionId", mentionId);
        event.put("documentId", articleId);
        event.put("documentVersion", articleVersion);
        ObjectNode observation = (ObjectNode) event.get("observation");
        observation.put("documentId", articleId);
        observation.put("documentVersion", articleVersion);
        observation.put("rawVersion", second ? SECOND_RAW : HandoffFixtures.RAW_VERSION);
        observation.put("page", 0);
        observation.put("ordinal", ordinal);
        events.add(event);
        if (representative) {
            rawIssue.set("representative", event.deepCopy());
        }
        return new VerifiedHandoff(rebuilt(typed, issues, evidence, articles), base.manifest(), base.manifestNode(), raw,
                base.receiptNode(), base.attemptsNode(), base.manifestDigest(), base.bundleDigest(), base.contentDigest());
    }

    private static byte[] resource(String name) throws IOException {
        try (InputStream in = HandoffSnapshotWriterTest.class.getClassLoader().getResourceAsStream("graph-handoff/" + name)) {
            return in.readAllBytes();
        }
    }
}
