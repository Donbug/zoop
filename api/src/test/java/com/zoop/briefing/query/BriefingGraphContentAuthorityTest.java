package com.zoop.briefing.query;

import com.zoop.common.exception.CustomException;
import com.zoop.common.exception.ErrorCode;
import com.zoop.graph.publication.GraphPublicationAuthority;
import com.zoop.graph.publication.GraphPublicationReader;
import com.zoop.graph.publication.GraphPublicationReader.Publication;
import com.zoop.graph.read.DisclosureExclusions;
import com.zoop.graph.read.DisclosureExclusions.ArticleTarget;
import com.zoop.graph.snapshot.PublicGraphSnapshot;
import com.zoop.graph.version.GraphVersionRecord;
import com.zoop.graph.version.GraphVersionRepository;
import java.util.List;
import java.util.Map;
import java.util.Optional;
import java.util.Set;
import org.junit.jupiter.api.Test;
import tools.jackson.databind.json.JsonMapper;
import tools.jackson.databind.node.ObjectNode;
import static org.junit.jupiter.api.Assertions.*;
import static org.mockito.ArgumentMatchers.*;
import static org.mockito.Mockito.*;

class BriefingGraphContentAuthorityTest {
    private static final String VERSION = "gv-" + "a".repeat(64);
    private static final String PRIOR = "gv-" + "b".repeat(64);
    private final GraphVersionRepository versions = mock(GraphVersionRepository.class);
    private final GraphPublicationReader publications = mock(GraphPublicationReader.class);
    private final GraphPublicationAuthority authority = mock(GraphPublicationAuthority.class);
    private final BriefingGraphContentAuthority gate = new BriefingGraphContentAuthority(versions, publications, authority);
    private final JsonMapper json = JsonMapper.builder().build();

    private PublicGraphSnapshot snapshot(String version) {
        var issue = new PublicGraphSnapshot.Issue("issue", "Published title", null, "unknown", null, "asserted",
                "action", "target", null, "zoop-public-projection-policy-3", List.of(), List.of("article"),
                List.of("evidence"), List.of(new PublicGraphSnapshot.MentionRef("mention", "article", "v1")),
                "mention", "2026-10-15T01:00:00Z");
        return new PublicGraphSnapshot(4, version, "publication",
                List.of(new PublicGraphSnapshot.Company("company", "Company", null, null)), List.of(issue),
                List.of(new PublicGraphSnapshot.Relation("relation", "INVOLVES", "issue", "company", null, null,
                        List.of("evidence"), List.of())),
                List.of(new PublicGraphSnapshot.Article("article", "v1", "Title", "https://example.invalid", "2026-10-15T01:00:00Z")),
                List.of(new PublicGraphSnapshot.Evidence("evidence", "article", "v1", 0, 5)));
    }

    private void bind(String version, DisclosureExclusions excluded) {
        bind(version, excluded, snapshot(version));
    }

    private void bind(String version, DisclosureExclusions excluded, PublicGraphSnapshot snapshot) {
        when(versions.find(version)).thenReturn(Optional.of(new GraphVersionRecord(version, 1, "snapshot", "artifact", "uri", "hash", false)));
        when(publications.read(version)).thenReturn(new Publication(version, "publication", "digest", null, null,
                null, null, snapshot, List.of(), null, Map.of(), Map.of()));
        doAnswer(call -> ((Publication) call.getArgument(0)).versionId().equals(version) ? excluded : DisclosureExclusions.NONE)
                .when(authority).current(any(Publication.class), eq("request"));
    }

    private ObjectNode payload() {
        var result = json.createObjectNode().put("graphVersion", VERSION);
        var item = result.putArray("items").addObject().put("eventId", "issue");
        item.putArray("evidenceIds").add("evidence");
        item.putArray("companies").addObject().put("id", "company").put("relationType", "INVOLVES");
        result.putObject("references").putArray("eventIds").add("issue");
        return result;
    }

    private ObjectNode candidate() {
        var result = json.createObjectNode().put("issueId", "personal-issue");
        result.putArray("sources").addObject().put("evidenceId", "evidence")
                .put("documentId", "article").put("documentVersion", "v1");
        result.putArray("companies").addObject().put("companyId", "company").putArray("evidenceIds").add("evidence");
        return result;
    }

    @Test void validDocumentGrantCannotRescueSourceIssueOrPublicationEvidenceExclusion() {
        var payload = payload();
        bind(VERSION, DisclosureExclusions.NONE);
        assertTrue(gate.context(VERSION, "request").allowsRound(payload, Set.of("evidence")));
        assertTrue(gate.context(VERSION, "request").allowsCandidate(candidate()));
        // Document grants are deliberately unchanged; the independent current graph overlay denies the content.
        bind(VERSION, new DisclosureExclusions(1, Set.of("issue"), Set.of(), Set.of()));
        assertFalse(gate.context(VERSION, "request").allowsRound(payload, Set.of("evidence")));
        assertFalse(gate.context(VERSION, "request").allowsCandidate(candidate()));
        bind(VERSION, new DisclosureExclusions(2, Set.of(), Set.of(), Set.of("evidence")));
        assertFalse(gate.context(VERSION, "request").allowsRound(payload, Set.of("evidence")));
        assertFalse(gate.context(VERSION, "request").allowsCandidate(candidate()));
    }

    @Test void revokingOriginalGraphSourceGrantWithDocumentGrantUnchangedWithholdsAllStoredViews() {
        bind(VERSION, new DisclosureExclusions(3, Set.of(), Set.of(), Set.of(),
                Set.of(new ArticleTarget("article", "v1"))));
        var context = gate.context(VERSION, "request");
        assertFalse(context.allowsRound(payload(), Set.of("evidence")));
        assertFalse(context.allowsCandidate(candidate()));
    }

    @Test void excludedRelationCannotBeRescuedByStillReadableIssueAndEvidence() {
        bind(VERSION, DisclosureExclusions.NONE);
        assertTrue(gate.context(VERSION, "request").allowsRound(payload(), Set.of("evidence")));
        assertTrue(gate.context(VERSION, "request").allowsCandidate(candidate()));
        bind(VERSION, new DisclosureExclusions(4, Set.of(), Set.of("relation"), Set.of()));
        assertFalse(gate.context(VERSION, "request").allowsRound(payload(), Set.of("evidence")));
        assertFalse(gate.context(VERSION, "request").allowsCandidate(candidate()));
    }

    @Test void excludedUnselectedIssueCannotStillSupplyMarketSummaryEvidence() {
        var published = snapshot(VERSION);
        var first = published.issues().getFirst();
        var hidden = new PublicGraphSnapshot.Issue("hidden", "Retained other title", null, "unknown", null,
                "asserted", "action", "target", null, "zoop-public-projection-policy-3", List.of(),
                List.of("article"), List.of("evidence"), List.of(new PublicGraphSnapshot.MentionRef("other", "article", "v1")),
                "other", "2026-10-15T01:00:00Z");
        var both = new PublicGraphSnapshot(4, VERSION, published.sourceBundleId(), published.companies(),
                List.of(first, hidden), published.relations(), published.articles(), published.evidence());
        bind(VERSION, DisclosureExclusions.NONE, both);
        assertTrue(gate.context(VERSION, "request").allowsRound(payload(), Set.of("evidence")));
        bind(VERSION, new DisclosureExclusions(5, Set.of("hidden"), Set.of(), Set.of()), both);
        assertFalse(gate.context(VERSION, "request").allowsRound(payload(), Set.of("evidence")));
    }

    @Test void previousRoundUsesItsOwnVersionAndMissingImportedProofIsUnavailable() {
        bind(VERSION, DisclosureExclusions.NONE);
        var previous = new DisclosureExclusions(1, Set.of("issue"), Set.of(), Set.of());
        bind(PRIOR, previous);
        assertTrue(gate.context(VERSION, "request").allowsRound(payload(), Set.of("evidence")));
        assertFalse(gate.context(PRIOR, "request").allowsRound(payload(), Set.of("evidence")));
        assertEquals(ErrorCode.SOURCE_UNAVAILABLE, assertThrows(CustomException.class,
                () -> gate.context("gv-" + "c".repeat(64), "request")).getErrorCode());
    }

    @Test void fixtureWithoutImportedVersionKeepsItsSeparateDocumentAuthorizationPath() {
        assertTrue(gate.context("synthetic-graph-v1", "request").allowsRound(payload(), Set.of("evidence")));
        verifyNoInteractions(publications, authority);
    }
}
