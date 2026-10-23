package com.zoop.graph.read;

import static com.zoop.graph.read.GraphReadFixtures.*;
import static org.junit.jupiter.api.Assertions.*;
import static org.mockito.Mockito.*;
import com.zoop.common.exception.CustomException;
import com.zoop.common.exception.ErrorCode;
import com.zoop.company.graph.CompanyGraphReadRequest;
import com.zoop.graph.snapshot.PublicGraphSnapshot;
import com.zoop.graph.version.*;
import java.time.*;
import java.util.*;
import org.junit.jupiter.api.Test;
import org.springframework.jdbc.core.namedparam.NamedParameterJdbcTemplate;

/** I1 and unrelated I2 share A/B. Every detail must see only I1, before SHARES_ISSUE is derived. */
class BriefingRoundScopeTest {
    private static final Instant NOW = Instant.parse("2026-10-16T12:00:00Z");

    private PublicGraphReader reader() {
        var source = snapshot("fixture-2026-10-08");
        var original = source.issues().stream().filter(i -> i.issueId().equals(HBM_SUPPLY)).findFirst().orElseThrow();
        var other = new PublicGraphSnapshot.Issue("outside", "outside headline", original.eventTime(), original.timePrecision(),
                original.period(), original.assertionStatus(), original.action(), original.target(), original.geography(),
                original.geographyPolicyVersion(), original.geographyEvidenceIds(), original.articleIds(), original.evidenceIds(),
                original.mentions(), original.representativeMentionId(), original.latestPublishedAt());
        var issues = new ArrayList<>(source.issues()); issues.add(other);
        var relations = new ArrayList<>(source.relations());
        source.relations().stream().filter(r -> r.source().equals(HBM_SUPPLY) && !r.relationType().equals("FOLLOWS"))
                .forEach(r -> relations.add(new PublicGraphSnapshot.Relation("outside-" + r.relationId(), r.relationType(),
                        "outside", r.target(), r.role(), r.assertionStatus(), r.evidenceIds(), r.basis())));
        var snapshot = new PublicGraphSnapshot(source.snapshotFormat(), source.versionId(), source.sourceBundleId(),
                source.companies(), issues, relations, source.articles(), source.evidence());
        var basis = new BriefingGraphLookup.Basis("round", source.versionId(), NOW, Map.of(HBM_SUPPLY, List.of(HYNIX, NVDA)));
        return new PublicGraphReader(new GraphVersionSelector(repository(), Clock.fixed(NOW, ZoneOffset.UTC),
                (id, request) -> basis), version -> snapshot, () -> DisclosureExclusions.NONE);
    }

    @Test void derivedRelationsCompanyAndEvidenceUseTheSameClosedScope() {
        var reader = reader();
        var full = reader.read(null, null, null).graph();
        var edgeId = DisplayGraph.edgeId("SHARES_ISSUE", HYNIX, NVDA);
        assertEquals(2, full.edges.get(edgeId).via().size(), "the counterexample contains both issues");
        var pinned = reader.read("round", null, null);
        var graph = pinned.graph();
        assertEquals(Set.of(HBM_SUPPLY), graph.issues.keySet());
        assertEquals(List.of(HBM_SUPPLY), graph.edges.get(edgeId).via());
        assertFalse(graph.edges.get(edgeId).summary().contains("2"));
        var relations = new GraphRelationService(reader, mock(NamedParameterJdbcTemplate.class));
        var detail = relations.getRelation(edgeId, "round", null, null, "r");
        assertEquals(List.of(HBM_SUPPLY), detail.via().stream().map(v -> v.id()).toList());
        var company = new GraphCompanySnapshotReader(reader).read(new CompanyGraphReadRequest(HYNIX, "round", null, null)).orElseThrow();
        assertEquals(List.of(HBM_SUPPLY), company.directIssues().stream().map(i -> i.issueId()).toList());
        assertTrue(company.structuralIssues().isEmpty());
        var span = graph.snapshot.evidence().get(0);
        var evidence = new GraphEvidenceSnapshotReader(reader).readRound("round", null, null, span.evidenceId(), null, "r").graph();
        assertEquals(List.of(HBM_SUPPLY), evidence.eventIds());
        assertEquals(ErrorCode.RESOURCE_NOT_FOUND, assertThrows(CustomException.class,
                () -> relations.getRelation(DisplayGraph.edgeId("INVOLVES", "outside", HYNIX), "round", null, null, "r")).getErrorCode());
    }
}
