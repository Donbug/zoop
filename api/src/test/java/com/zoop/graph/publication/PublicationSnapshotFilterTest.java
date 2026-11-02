package com.zoop.graph.publication;

import java.time.Instant;
import java.util.List;
import java.util.Set;
import com.zoop.graph.read.DisclosureExclusions;
import com.zoop.graph.read.GraphSnapshotFilter;
import com.zoop.graph.snapshot.PublicGraphSnapshot;
import org.junit.jupiter.api.Test;
import static org.junit.jupiter.api.Assertions.*;

class PublicationSnapshotFilterTest {
    @Test
    void exactArticleWithdrawalRemovesItsMentionsEvidenceAndPublicationMetadata() {
        var source = PublicationMergerTest.source(0, "issue", "Headline").projection();
        var core = source.issues().getFirst(); var article = source.articles().getFirst();
        String incidental = "doc-" + "e".repeat(64), evidence = "ev-" + "f".repeat(64), version = "d".repeat(64);
        var issue = new PublicGraphSnapshot.Issue(core.issueId(), core.label(), core.eventTime(), core.timePrecision(), core.period(),
                core.assertionStatus(), core.action(), core.target(), core.geography(), core.geographyPolicyVersion(), core.geographyEvidenceIds(),
                List.of(article.articleId(), incidental), List.of(core.evidenceIds().getFirst(), evidence),
                List.of(new PublicGraphSnapshot.MentionRef("later", incidental, version)), "later", "2026-10-20");
        var snapshot = new PublicGraphSnapshot(3, source.versionId(), source.sourceBundleId(), source.companies(), List.of(issue), source.relations(),
                List.of(article, new PublicGraphSnapshot.Article(incidental, version, "Withdrawn article", "https://example.invalid/withdrawn", "2026-10-20")),
                List.of(source.evidence().getFirst(), new PublicGraphSnapshot.Evidence(evidence, incidental, version, 0, 1)));
        var overlay = new DisclosureExclusions(1, Set.of(), Set.of(), Set.of(), Set.of(new DisclosureExclusions.ArticleTarget(incidental, version)));
        var visible = GraphSnapshotFilter.apply(snapshot, null, overlay);
        assertEquals(List.of(article), visible.articles());
        assertEquals(source.evidence(), visible.evidence());
        assertEquals(List.of(article.articleId()), visible.issues().getFirst().articleIds());
        assertEquals(List.of(), visible.issues().getFirst().mentions());
        assertNull(visible.issues().getFirst().representativeMentionId());
        assertEquals("2026-10-01", visible.issues().getFirst().latestPublishedAt());
    }

    @Test
    void explicitUnknownGeographyKeepsCoreProofWhileUnknownPublicationTimeStaysConservative() {
        var source = PublicationMergerTest.source(0, "issue", "Headline").projection(); var old = source.issues().getFirst();
        var unknown = new PublicGraphSnapshot.Issue(old.issueId(), old.label(), null, "unknown", null, old.assertionStatus(), old.action(), old.target(),
                null, "zoop-public-projection-policy-3", List.of(), old.articleIds(), old.evidenceIds(), List.of(), null, null);
        var article = source.articles().getFirst();
        var snapshot = new PublicGraphSnapshot(PublicGraphSnapshot.EXPLICIT_UNKNOWN_FORMAT, source.versionId(), source.sourceBundleId(), source.companies(),
                List.of(unknown), source.relations(), List.of(new PublicGraphSnapshot.Article(article.articleId(), article.version(), article.title(), article.url(), null)), source.evidence());
        assertEquals(List.of("issue"), GraphSnapshotFilter.apply(snapshot, null, DisclosureExclusions.NONE).issues().stream()
                .map(PublicGraphSnapshot.Issue::issueId).toList());
        assertEquals(List.of(), GraphSnapshotFilter.apply(snapshot, Instant.parse("2026-10-31T00:00:00Z"), DisclosureExclusions.NONE).issues());
    }
}
