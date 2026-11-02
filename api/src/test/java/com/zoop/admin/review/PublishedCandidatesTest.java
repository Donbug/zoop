package com.zoop.admin.review;

import static org.junit.jupiter.api.Assertions.*;
import static org.mockito.ArgumentMatchers.*;
import static org.mockito.Mockito.*;

import com.zoop.common.exception.CustomException;
import com.zoop.common.exception.ErrorCode;
import com.zoop.common.json.StrictJson;
import com.zoop.document.evidence.service.EvidenceService;
import com.zoop.graph.importer.MentionIds;
import com.zoop.graph.publication.GraphPublicationAuthority;
import com.zoop.graph.publication.GraphPublicationReader;
import com.zoop.graph.publication.GraphPublicationReader.*;
import com.zoop.graph.read.DisclosureExclusions;
import com.zoop.graph.read.PublicGraphReader;
import com.zoop.graph.snapshot.PublicGraphSnapshot;
import com.zoop.graph.snapshot.PublicGraphSnapshot.*;
import com.zoop.graph.version.GraphVersionRecord;
import com.zoop.graph.version.GraphVersionSelector;
import com.zoop.graph.version.SelectedGraphVersion;
import java.time.Instant;
import java.util.*;
import java.util.concurrent.atomic.AtomicReference;
import org.junit.jupiter.api.Test;

class PublishedCandidatesTest {
    private static final Instant NOW = Instant.parse("2026-10-31T00:00:00Z");

    @Test
    void mergedPublicIdsKeepEveryNativeCandidateAndSkipLegacyApprovalClaims() {
        Publication publication = publication();
        var shown = PublishedCandidates.read(publication, Set.of("public-edge"), Set.of("public-issue"), ignored -> true);

        assertEquals(Set.of("s3-a\nrc-a", "s3-b\nrc-b"), shown.relations());
        assertEquals(Set.of("s2-a\nevc-a", "s2-b\nevc-b"), shown.events());
        assertEquals("public-issue", shown.publicIssueId("snapshot-a"));
        assertEquals("public-issue", shown.publicIssueId("snapshot-b"));
        assertNull(shown.publicIssueId("snapshot-legacy"));
        assertFalse(shown.relation("s3-legacy", "rc-legacy"));
        assertFalse(shown.event("s2-legacy", "evc-legacy"));
        assertTrue(shown.excludedRelations().isEmpty());
    }

    @Test
    void correctedRelationPublishesOnlyTheSelectedOriginalCandidate() {
        Publication publication = publication();
        var selection = StrictJson.newObject().put("relationId", "public-edge");
        selection.set("takeFrom", StrictJson.newObject().put("sourceVersionId", "source-b").put("relationId", "edge-b"));
        ((tools.jackson.databind.node.ObjectNode) publication.effectiveDecisions().node())
                .set("relationSelections", StrictJson.newArray().add(selection));
        var shown = PublishedCandidates.read(publication, Set.of("public-edge"), Set.of("public-issue"), ignored -> true);
        assertEquals(Set.of("s3-b\nrc-b"), shown.relations());
        assertEquals(Set.of("s3-a\nrc-a"), shown.excludedRelations());
        assertEquals(Set.of("s2-a\nevc-a", "s2-b\nevc-b"), shown.events());
    }

    @Test
    void visibleMergedEventDoesNotRescueAWithdrawnOriginalCandidate() {
        var shown = PublishedCandidates.read(publication(), Set.of(), Set.of("public-issue"), id -> !id.equals("e-b"));
        assertEquals(Set.of("s2-a\nevc-a"), shown.events());
        assertEquals(Set.of("s2-b\nevc-b"), shown.excludedEvents());
        assertEquals("public-issue", shown.publicIssueId("snapshot-b"));
    }

    @Test
    void exclusionsFollowMappedPublicItemsAcrossAllOriginalLeaves() {
        var shown = PublishedCandidates.read(publication(), Set.of(), Set.of(), ignored -> true);
        assertTrue(shown.relations().isEmpty());
        assertTrue(shown.events().isEmpty());
        assertEquals(Set.of("s3-a\nrc-a", "s3-b\nrc-b"), shown.excludedRelations());
        assertEquals(Set.of("s2-a\nevc-a", "s2-b\nevc-b"), shown.excludedEvents());
        assertEquals("public-issue", shown.publicIssueId("snapshot-b"));
    }

    @Test
    void currentDenialIsAppliedOnTheNextReadWithoutWaitingForACacheDeadline() {
        Publication publication = publication();
        var selector = mock(GraphVersionSelector.class);
        when(selector.select(any(), any(), any(), any())).thenReturn(selected());
        var proofs = mock(GraphPublicationReader.class);
        when(proofs.read(eq("publication-version"), any())).thenReturn(publication);
        var authority = mock(GraphPublicationAuthority.class);
        AtomicReference<DisclosureExclusions> overlay = new AtomicReference<>(DisclosureExclusions.NONE);
        when(authority.current(eq(publication), any())).thenAnswer(call -> overlay.get());
        var reader = new PublicGraphReader(selector, ignored -> publication.snapshot(), ignored -> DisclosureExclusions.NONE,
                proofs, authority);
        var evidence = mock(EvidenceService.class);
        when(evidence.graphPublication(anyString(), anyString())).thenReturn(publication);
        when(evidence.shownNow(anyString(), anyString(), any(), anyString())).thenReturn(true);
        var candidates = new PublishedCandidates(reader, evidence);

        assertTrue(candidates.current("before").orElseThrow().event("s2-b", "evc-b"));
        overlay.set(new DisclosureExclusions(1, Set.of("public-issue"), Set.of(), Set.of(),
                Set.of(new DisclosureExclusions.ArticleTarget("article-a", "v1"))));
        var denied = candidates.current("withdrawn").orElseThrow();
        assertFalse(denied.event("s2-b", "evc-b"));
        assertTrue(denied.excludedEvent("s2-a", "evc-a"));
        assertTrue(denied.excludedRelation("s3-b", "rc-b"));
        when(authority.current(eq(publication), any())).thenThrow(new CustomException(ErrorCode.SOURCE_UNAVAILABLE));
        assertTrue(candidates.current("outage").isEmpty());
    }

    @Test
    void selectedOwnerDenialCannotBeRescuedByAnotherVisibleMention() {
        Publication publication = publication();
        var reader = mock(PublicGraphReader.class);
        when(reader.read(any(), any(), any(), any())).thenReturn(new PublicGraphReader.Pinned(selected(),
                com.zoop.graph.read.DisplayGraph.of(publication.snapshot())));
        var evidence = mock(EvidenceService.class);
        when(evidence.graphPublication(any(), any())).thenReturn(publication);
        when(evidence.shownNow(anyString(), anyString(), any(), anyString())).thenReturn(true);
        when(evidence.shownNow(eq("e-a"), anyString(), any(), anyString())).thenReturn(false);
        var shown = new PublishedCandidates(reader, evidence).current("denied").orElseThrow();
        assertTrue(shown.events().isEmpty());
        assertEquals(Set.of("s2-a\nevc-a", "s2-b\nevc-b"), shown.excludedEvents());
    }

    private static SelectedGraphVersion selected() {
        return new SelectedGraphVersion(new GraphVersionRecord("publication-version", 4, "snapshot", "artifact", "uri",
                "a".repeat(64), true), NOW, false);
    }

    private static Publication publication() {
        List<Contribution> sources = new ArrayList<>();
        List<MentionRef> mentions = new ArrayList<>();
        List<Article> articles = new ArrayList<>();
        List<Evidence> evidence = new ArrayList<>();
        List<IssueRef> members = new ArrayList<>();
        List<RelationRef> relations = new ArrayList<>();
        for (String suffix : List.of("a", "b", "legacy")) {
            String article = "article-" + suffix;
            var mention = new MentionRef(MentionIds.of(article, "v1", "m"), article, "v1");
            var issue = issue("issue-" + suffix, List.of(mention), List.of(article), List.of("e-" + suffix));
            var relation = new Relation("edge-" + suffix, "INVOLVES", issue.issueId(), "company", null, null,
                    List.of("e-" + suffix), List.of());
            var storedArticle = new Article(article, "v1", article, "https://example.invalid/" + suffix, NOW.toString());
            var span = new Evidence("e-" + suffix, article, "v1", 0, 1);
            var projection = new PublicGraphSnapshot(4, "source-" + suffix, "handoff-" + suffix,
                    List.of(new Company("company", "Company", null, null)), List.of(issue), List.of(relation),
                    List.of(storedArticle), List.of(span));
            var bundle = StrictJson.parseObject("""
                    {"schemaVersion":"zoop-graph-handoff-bundle-9","relations":[
                      {"id":"edge-%1$s","sourceRefs":[{"kind":"s3-relation","jobId":"s3-%1$s","id":"rc-%1$s"}]}],
                     "issues":[{"id":"issue-%1$s","sourceEvents":[
                       {"kind":"event-candidate","ref":"evc-%1$s","upstream":{"jobId":"s2-%1$s"}},
                       {"kind":"snapshot-event","ref":"snapshot-%1$s"}],
                       "mentions":[{"articleId":"article-%1$s","articleVersion":"v1","mentionId":"m","evidenceIds":["e-%1$s"]}]}]}
                    """.formatted(suffix));
            if (suffix.equals("legacy")) {
                ((tools.jackson.databind.node.ObjectNode) bundle.node()).put("schemaVersion",
                        com.zoop.graph.importer.LegacyRealPackage.METADATA_BUNDLE_SCHEMA);
                ((tools.jackson.databind.node.ObjectNode) bundle.objects("relations").getFirst().node()).remove("sourceRefs");
                ((tools.jackson.databind.node.ObjectNode) bundle.objects("issues").getFirst().node()).remove("sourceEvents");
            }
            var source = new Contribution("source-" + suffix, "handoff-" + suffix,
                    suffix.equals("legacy") ? "legacy-real" : "native", null, null, projection, bundle);
            sources.add(source); mentions.add(mention); articles.add(storedArticle); evidence.add(span);
            members.add(source.issueRef(issue.issueId())); relations.add(new RelationRef(source.sourceVersionId(), relation.relationId()));
        }
        IssueRef owner = members.getFirst();
        var issue = issue("public-issue", mentions, articles.stream().map(Article::articleId).toList(),
                evidence.stream().map(Evidence::evidenceId).toList());
        var relation = new Relation("public-edge", "INVOLVES", issue.issueId(), "company", null, null,
                issue.evidenceIds(), List.of());
        var snapshot = new PublicGraphSnapshot(4, "publication-version", "publication", sources.getFirst().projection().companies(),
                List.of(issue), List.of(relation), articles, evidence);
        return new Publication("publication-version", "publication", "digest", null, null, null, null, snapshot,
                sources, StrictJson.parseObject("{\"schemaVersion\":\"zoop-graph-publication-decisions-1\",\"issueMappings\":[],\"fieldSelections\":[],\"relationSelections\":[]}"), Map.of(issue.issueId(), new IssueOwners(issue.issueId(), members,
                        Map.of("label", owner, "action", owner, "target", owner, "assertionStatus", owner,
                                "eventTime", owner, "period", owner, "geography", owner))),
                Map.of(relation.relationId(), new RelationOwners(relation.relationId(), relations, issue.issueId(), "company")));
    }

    private static Issue issue(String id, List<MentionRef> mentions, List<String> articles, List<String> evidence) {
        return new Issue(id, "Selected headline", null, "unknown", null, "occurred", "action", null, null,
                "zoop-public-projection-policy-3", List.of(), articles, evidence, mentions,
                mentions.getFirst().mentionId(), NOW.toString());
    }
}
