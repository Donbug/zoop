package com.zoop.briefing.query;

import com.zoop.briefing.replay.BriefingReplayReadPolicy;
import com.zoop.briefing.storage.BriefingRound;
import com.zoop.document.evidence.config.DocumentReadProperties;
import com.zoop.graph.publication.GraphPublicationAuthority;
import com.zoop.graph.publication.GraphPublicationReader;
import com.zoop.graph.publication.GraphPublicationReader.Publication;
import com.zoop.graph.read.DisclosureExclusions;
import com.zoop.graph.read.DisclosureExclusions.ArticleTarget;
import com.zoop.graph.snapshot.PublicGraphSnapshot;
import com.zoop.graph.version.GraphVersionRecord;
import com.zoop.graph.version.GraphVersionRepository;
import java.nio.file.Files;
import java.nio.file.Path;
import java.sql.ResultSet;
import java.sql.SQLException;
import java.time.Clock;
import java.time.Instant;
import java.time.LocalDate;
import java.time.ZoneOffset;
import java.util.List;
import java.util.Map;
import java.util.Optional;
import java.util.Set;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.io.TempDir;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.jdbc.core.RowMapper;
import tools.jackson.databind.JsonNode;
import tools.jackson.databind.json.JsonMapper;
import tools.jackson.databind.node.ObjectNode;
import static org.junit.jupiter.api.Assertions.*;
import static org.mockito.ArgumentMatchers.*;
import static org.mockito.Mockito.*;

/** Valid S1 remains necessary, but cannot override a present S2 or source-exclusion denial. */
class DocumentBriefingPublicationAccessTest {
    private static final String GRAPH = "gv-" + "a".repeat(64);
    private static final String PRIOR = "gv-" + "b".repeat(64);
    @TempDir Path temporary;
    private final JsonMapper json = JsonMapper.builder().build();
    private final GraphVersionRepository versions = mock(GraphVersionRepository.class);
    private final GraphPublicationReader publications = mock(GraphPublicationReader.class);
    private final GraphPublicationAuthority authority = mock(GraphPublicationAuthority.class);

    private PublicGraphSnapshot snapshot(String version) {
        return new PublicGraphSnapshot(4, version, "publication", List.of(), List.of(new PublicGraphSnapshot.Issue(
                "issue", "Title", null, "unknown", null, "asserted", "action", "target", null,
                "zoop-public-projection-policy-3", List.of(), List.of("article"), List.of("evidence"),
                List.of(new PublicGraphSnapshot.MentionRef("mention", "article", "v1")), "mention", "2026-10-15T01:00:00Z")),
                List.of(), List.of(new PublicGraphSnapshot.Article("article", "v1", "Title", "https://example.invalid", "2026-10-15T01:00:00Z")),
                List.of(new PublicGraphSnapshot.Evidence("evidence", "article", "v1", 0, 5)));
    }

    private void bind(String version, DisclosureExclusions excluded) {
        when(versions.find(version)).thenReturn(Optional.of(new GraphVersionRecord(version, 1, "snapshot", "artifact", "uri", "hash", false)));
        when(publications.read(version)).thenReturn(new Publication(version, "publication", "digest", null, null, null, null,
                snapshot(version), List.of(), null, Map.of(), Map.of()));
        doAnswer(call -> {
            Publication publication = call.getArgument(0);
            return publication.versionId().equals(version) ? excluded : DisclosureExclusions.NONE;
        }).when(authority).current(any(Publication.class), eq("test"));
    }

    private BriefingRound round(String version, JsonNode comparison) {
        Instant cutoff = Instant.parse("2026-10-15T08:30:00Z");
        ObjectNode payload = json.createObjectNode().put("graphVersion", version);
        payload.putObject("references").putArray("evidenceIds").add("evidence");
        ((ObjectNode) payload.path("references")).putArray("eventIds").add("issue");
        payload.putArray("items").addObject().put("eventId", "issue").putArray("evidenceIds").add("evidence");
        ((ObjectNode) payload.path("items").get(0)).putArray("documentSentiments");
        ((ObjectNode) payload.path("items").get(0)).putArray("companies");
        ((ObjectNode) payload.path("items").get(0)).putObject("summary").putArray("evidenceIds").add("evidence");
        ObjectNode publicSnapshot = json.createObjectNode();
        publicSnapshot.putObject("marketSummary").put("status", "unavailable");
        publicSnapshot.putArray("sourceBindings").addObject().put("documentId", "article").put("documentVersion", "v1")
                .put("grantId", "brf-test-grant").put("grantRevision", "synthetic-v1")
                .putArray("recipients").add("authored-replay");
        return new BriefingRound("round", LocalDate.parse("2026-10-15"), "evening", cutoff, null, cutoff, true,
                "published", cutoff.plusSeconds(1), cutoff, version, payload, publicSnapshot, comparison);
    }

    private DocumentBriefingContentAccess access(BriefingRound prior) throws Exception {
        Path grants = temporary.resolve("grants.json");
        try (var input = getClass().getClassLoader().getResourceAsStream("briefing/grants.json")) {
            assertNotNull(input);
            Files.copy(input, grants);
        }
        var jdbc = new JdbcTemplate() {
            @Override public <T> List<T> query(String sql, RowMapper<T> mapper, Object... args) {
                try {
                    ResultSet rs = mock(ResultSet.class);
                    when(rs.getString("provider")).thenReturn("authored-replay");
                    when(rs.getString("article_id")).thenReturn("article");
                    when(rs.getString("article_version")).thenReturn("v1");
                    if (prior != null) {
                        when(rs.getString("published_payload")).thenReturn(prior.payload().toString());
                        when(rs.getString("public_snapshot")).thenReturn(prior.publicSnapshot().toString());
                    }
                    return List.of(mapper.mapRow(rs, 0));
                } catch (SQLException error) { throw new IllegalStateException(error); }
            }
        };
        var graph = new BriefingGraphContentAuthority(versions, publications, authority);
        return new DocumentBriefingContentAccess(jdbc, new DocumentReadProperties(grants.toString(), null, null),
                Clock.fixed(Instant.parse("2026-10-31T01:00:00Z"), ZoneOffset.UTC), BriefingReplayReadPolicy.disabled(), graph);
    }

    @Test void validDocumentGrantDoesNotRescueExcludedIssueEvidenceOrRevokedSource() throws Exception {
        var round = round(GRAPH, null);
        var access = access(null);
        bind(GRAPH, DisclosureExclusions.NONE);
        assertTrue(access.mayRead(round, "test"));
        bind(GRAPH, new DisclosureExclusions(1, Set.of("issue"), Set.of(), Set.of()));
        assertFalse(access.mayRead(round, "test"));
        bind(GRAPH, new DisclosureExclusions(2, Set.of(), Set.of(), Set.of("evidence")));
        assertFalse(access.mayRead(round, "test"));
        bind(GRAPH, new DisclosureExclusions(3, Set.of(), Set.of(), Set.of(), Set.of(new ArticleTarget("article", "v1"))));
        assertFalse(access.mayRead(round, "test"));
        bind(GRAPH, DisclosureExclusions.NONE);
        assertTrue(access.mayRead(round, "test"));
    }

    @Test void retainedComparisonRechecksPreviousGraphVersionEvenWhenCurrentS1AndGraphRemainValid() throws Exception {
        var previous = round(PRIOR, null);
        ObjectNode comparison = json.createObjectNode().put("status", "available").put("morningRoundId", "previous");
        var current = round(GRAPH, comparison);
        var access = access(previous);
        bind(GRAPH, DisclosureExclusions.NONE);
        bind(PRIOR, new DisclosureExclusions(1, Set.of("issue"), Set.of(), Set.of()));
        assertFalse(access.mayRead(current, "test"));
        bind(PRIOR, DisclosureExclusions.NONE);
        assertTrue(access.mayRead(current, "test"));
    }
}
