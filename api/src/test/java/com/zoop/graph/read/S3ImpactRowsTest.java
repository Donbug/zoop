package com.zoop.graph.read;

import static org.junit.jupiter.api.Assertions.*;
import java.util.*;
import com.zoop.common.json.StrictJson;
import com.zoop.common.json.StrictJson.Obj;
import com.zoop.graph.snapshot.PublicGraphSnapshot.Relation;
import com.zoop.graph.publication.GraphPublicationReader.*;
import com.zoop.graph.snapshot.PublicGraphSnapshot;
import org.junit.jupiter.api.Test;
import tools.jackson.databind.node.ObjectNode;

class S3ImpactRowsTest {
    static ObjectNode bundle() throws Exception {
        try (var in = S3ImpactRowsTest.class.getResourceAsStream("/graph-handoff/export-impacts.json")) {
            return (ObjectNode) StrictJson.parseObject(in.readAllBytes()).object("bundle").node().deepCopy();
        }
    }
    static List<Relation> visible(ObjectNode b) {
        return Obj.of(b).objects("relations").stream().filter(r -> "INVOLVES".equals(r.string("type")))
                .map(r -> new Relation(r.string("id"), r.string("type"), r.string("source"), r.string("target"), null, null,
                        r.strings("evidenceIds"), List.of())).toList();
    }
    static ObjectNode verified(ObjectNode b) {
        for (var row : b.path("impacts")) if ("verified".equals(row.path("status").asString())) return (ObjectNode) row;
        throw new AssertionError();
    }
    @Test void readsTheTeamProducerFixtureWithoutAggregatingConflictingSourceRowsOrPublishingProposal() throws Exception {
        var b = bundle(); var rows = S3ImpactRows.read(Obj.of(b), visible(b));
        assertEquals(6, rows.size());
        assertEquals(List.of("negative", "positive", "undetermined"), rows.stream().filter(r -> r.label() != null).map(S3ImpactRows.Row::label).sorted().toList());
        assertTrue(rows.stream().allMatch(r -> r.provenance().executionMode().equals("replay")));
        assertEquals(2, rows.stream().map(S3ImpactRows.Row::relationId).distinct().count());
    }
    @Test void aLegacyReceiptMeansAbsentNotUndeterminedAndUnknownFutureSchemasFailClosed() throws Exception {
        var b = bundle(); b.put("schemaVersion", "zoop-graph-handoff-bundle-5"); b.remove("impacts");
        assertTrue(S3ImpactRows.read(Obj.of(b), visible(b)).isEmpty());
        b.put("schemaVersion", "zoop-graph-handoff-bundle-10");
        assertThrows(StrictJson.Malformed.class, () -> S3ImpactRows.read(Obj.of(b), visible(b)));
    }
    @Test void rejectsAStoredLabelThatDiffersFromTheVerifierEffects() throws Exception {
        var b = bundle(); verified(b).put("label", "negative");
        assertThrows(StrictJson.Malformed.class, () -> S3ImpactRows.read(Obj.of(b), visible(b)));
    }
    @Test void insufficientTargetIsUndeterminedEvenWithPositiveQuotes() throws Exception {
        var b = bundle(); verified(b).put("targetVerdict", "insufficient").put("label", "undetermined");
        assertEquals("undetermined", S3ImpactRows.read(Obj.of(b), visible(b)).stream().filter(r -> r.label() != null).findFirst().orElseThrow().label());
    }
    @Test void rejectsForeignIssueCompanyOrSourceBindings() throws Exception {
        for (String field : List.of("issueId", "companyId")) {
            var b = bundle(); verified(b).put(field, "foreign");
            assertThrows(StrictJson.Malformed.class, () -> S3ImpactRows.read(Obj.of(b), visible(b)));
        }
        var b = bundle(); ((ObjectNode) verified(b).path("sourceRelation")).put("jobId", "foreign");
        assertThrows(StrictJson.Malformed.class, () -> S3ImpactRows.read(Obj.of(b), visible(b)));
    }
    @Test void rejectsMissingDuplicateAndCrossSideEvidence() throws Exception {
        var b = bundle(); var row = verified(b); var effects = (ObjectNode) row.path("effects");
        effects.withArray("negative").add(effects.path("positive").get(0).asString());
        assertThrows(StrictJson.Malformed.class, () -> S3ImpactRows.read(Obj.of(b), visible(b)));
        var empty = bundle(); empty.withArray("impacts").remove(0);
        assertThrows(StrictJson.Malformed.class, () -> S3ImpactRows.read(Obj.of(empty), visible(empty)));
        var duplicate = bundle(); duplicate.withArray("impacts").add(duplicate.path("impacts").get(0).deepCopy());
        assertThrows(StrictJson.Malformed.class, () -> S3ImpactRows.read(Obj.of(duplicate), visible(duplicate)));
    }
    @Test void rejectsEffectsOutsideTheRelationsOwnArticleVersion() throws Exception {
        var b = bundle(); var id = verified(b).path("effects").path("positive").get(0).asString();
        for (var e : b.path("evidence")) if (id.equals(e.path("id").asString())) ((ObjectNode) e).put("articleVersion", "foreign");
        assertThrows(StrictJson.Malformed.class, () -> S3ImpactRows.read(Obj.of(b), visible(b)));
    }
    @Test void nonVerifiedRowsCannotCarryALabelAndSyntheticReplayCannotClaimLiveProviderProvenance() throws Exception {
        var b = bundle(); ((ObjectNode) b.path("impacts").get(0)).put("label", "positive");
        assertThrows(StrictJson.Malformed.class, () -> S3ImpactRows.read(Obj.of(b), visible(b)));
        var p = bundle(); ((ObjectNode) p.path("sources").get(0).path("provenance")).put("executionMode", "live");
        assertThrows(StrictJson.Malformed.class, () -> S3ImpactRows.read(Obj.of(p), visible(p)));
    }

    @Test void nativeNineKeepsTheExistingImpactProofAndLegacyMetadataAddsNoNativeApproval() throws Exception {
        var b = bundle(); b.put("schemaVersion", "zoop-graph-handoff-bundle-9");
        assertEquals(6, S3ImpactRows.read(Obj.of(b), visible(b)).size());
        b.put("schemaVersion", com.zoop.graph.importer.LegacyRealPackage.METADATA_BUNDLE_SCHEMA);
        assertTrue(S3ImpactRows.read(Obj.of(b), visible(b)).isEmpty());
    }

    @Test void composedRowsProveOriginalEndpointsAndPreserveEveryLeavesVerdicts() throws Exception {
        Publication publication = composed();
        var rows = S3ImpactRows.read(publication, publication.snapshot().relations());
        assertEquals(12, rows.size());
        assertEquals(12, rows.stream().map(r -> r.relationId() + ":" + r.key()).distinct().count());
        assertEquals(List.of("negative", "negative", "positive", "positive", "undetermined", "undetermined"),
                rows.stream().map(S3ImpactRows.Row::label).filter(Objects::nonNull).sorted().toList());
        assertTrue(rows.stream().allMatch(r -> r.provenance().executionMode().equals("replay")));
        assertEquals(2, rows.stream().map(S3ImpactRows.Row::relationId).distinct().count());

        var incoming = publication.source("source-b");
        for (var row : incoming.bundle().objects("impacts"))
            ((ObjectNode) row.node()).put("issueId", "public:" + row.string("issueId").replace("incoming:", "issue:"));
        assertThrows(StrictJson.Malformed.class, () -> S3ImpactRows.read(publication, publication.snapshot().relations()),
                "public ids cannot replace the original verifier's membership proof");
    }

    @Test void relationCorrectionSelectsItsOriginalAssessmentWithoutDroppingRetainedOwners() throws Exception {
        var publication = composed();
        var selections = StrictJson.newArray();
        for (var relation : publication.snapshot().relations()) {
            var selection = StrictJson.newObject().put("relationId", relation.relationId());
            selection.set("takeFrom", StrictJson.newObject().put("sourceVersionId", "source-a").put("relationId", relation.relationId()));
            selections.add(selection);
        }
        ((ObjectNode) publication.effectiveDecisions().node()).set("relationSelections", selections);
        verified((ObjectNode) publication.source("source-b").bundle().node()).put("targetVerdict", "insufficient").put("label", "undetermined");
        var rows = S3ImpactRows.read(publication, publication.snapshot().relations());
        assertEquals(6, rows.size());
        assertEquals(List.of("negative", "positive", "undetermined"), rows.stream()
                .map(S3ImpactRows.Row::label).filter(Objects::nonNull).sorted().toList());
        assertTrue(rows.stream().allMatch(r -> r.key().startsWith("source-a\n")));
        assertTrue(publication.relationSources().values().stream().allMatch(o -> o.sources().size() == 2));
    }

    static Publication composed() throws Exception {
        var first = bundle();
        var second = (ObjectNode) StrictJson.parseObject(first.toString().replace("issue:", "incoming:")).node();
        List<Contribution> contributions = new ArrayList<>();
        Map<String, IssueOwners> issues = new HashMap<>();
        Map<String, RelationOwners> relationOwners = new HashMap<>();
        List<Relation> publicRelations = new ArrayList<>();
        for (var entry : Map.of("source-a", first, "source-b", second).entrySet().stream()
                .sorted(Map.Entry.comparingByKey()).toList()) {
            var originalRelations = visible(entry.getValue());
            var original = projection(entry.getKey(), Obj.of(entry.getValue()));
            var contribution = new Contribution(entry.getKey(), original.sourceBundleId(), "native", null, null,
                    original, Obj.of(entry.getValue()));
            contributions.add(contribution);
            for (Relation relation : originalRelations) {
                String publicIssue = "public:" + relation.source().replace("incoming:", "issue:");
                var issueRef = contribution.issueRef(relation.source());
                var previousIssue = issues.get(publicIssue);
                List<IssueRef> members = new ArrayList<>(previousIssue == null ? List.of() : previousIssue.members());
                members.add(issueRef);
                IssueRef headline = members.getFirst();
                issues.put(publicIssue, new IssueOwners(publicIssue, members, Map.of("label", headline, "action", headline,
                        "target", headline, "assertionStatus", headline, "eventTime", headline, "period", headline, "geography", headline)));
                var previousRelation = relationOwners.get(relation.relationId());
                List<RelationRef> owners = new ArrayList<>(previousRelation == null ? List.of() : previousRelation.sources());
                owners.add(new RelationRef(contribution.sourceVersionId(), relation.relationId()));
                relationOwners.put(relation.relationId(), new RelationOwners(relation.relationId(), owners, publicIssue, relation.target()));
                if (previousRelation == null) publicRelations.add(new Relation(relation.relationId(), relation.relationType(),
                        publicIssue, relation.target(), relation.role(), relation.assertionStatus(), relation.evidenceIds(), relation.basis()));
            }
        }
        var empty = new PublicGraphSnapshot(4, "legacy-source", "legacy", List.of(), List.of(), List.of(), List.of(), List.of());
        contributions.addFirst(new Contribution("legacy-source", "legacy", "legacy-real", null, null, empty,
                StrictJson.parseObject("{\"schemaVersion\":\"" + com.zoop.graph.importer.LegacyRealPackage.METADATA_BUNDLE_SCHEMA + "\"}")));
        var basis = contributions.get(1).projection();
        var publicIssues = basis.issues().stream().map(i -> new PublicGraphSnapshot.Issue("public:" + i.issueId(), i.label(),
                i.eventTime(), i.timePrecision(), i.period(), i.assertionStatus(), i.action(), i.target(), i.geography(),
                i.geographyPolicyVersion(), i.geographyEvidenceIds(), i.articleIds(), i.evidenceIds(), i.mentions(),
                i.representativeMentionId(), i.latestPublishedAt())).toList();
        var snapshot = new PublicGraphSnapshot(4, "publication-version", "publication", basis.companies(), publicIssues, publicRelations,
                basis.articles(), basis.evidence());
        return new Publication(snapshot.versionId(), "publication", "digest", null, null, null, null, snapshot, contributions,
                StrictJson.parseObject("{\"schemaVersion\":\"zoop-graph-publication-decisions-1\",\"issueMappings\":[],\"fieldSelections\":[],\"relationSelections\":[]}"), issues, relationOwners);
    }

    private static PublicGraphSnapshot projection(String version, Obj bundle) {
        var articles = bundle.objects("articles").stream().map(a -> new PublicGraphSnapshot.Article(a.string("articleId"),
                a.string("articleVersion"), a.string("title"), a.string("url"), a.stringOrNull("publishedAt"))).toList();
        var evidence = bundle.objects("evidence").stream().map(e -> new PublicGraphSnapshot.Evidence(e.string("id"),
                e.string("articleId"), e.string("articleVersion"), e.count("start"), e.count("end"))).toList();
        var issues = bundle.objects("issues").stream().map(i -> {
            var mentions = i.objects("mentions").stream().map(m -> new PublicGraphSnapshot.MentionRef(
                    com.zoop.graph.importer.MentionIds.of(m.string("articleId"), m.string("articleVersion"), m.string("mentionId")),
                    m.string("articleId"), m.string("articleVersion"))).toList();
            var geography = i.object("geography");
            return new PublicGraphSnapshot.Issue(i.string("id"), i.string("title"), i.stringOrNull("eventTime"),
                    i.string("timePrecision"), i.stringOrNull("period"), i.string("assertionStatus"), i.string("action"),
                    i.stringOrNull("target"), geography.string("value"), geography.string("policyVersion"), geography.strings("evidenceIds"),
                    mentions.stream().map(PublicGraphSnapshot.MentionRef::articleId).distinct().toList(), i.strings("evidenceIds"),
                    mentions, null, "2026-10-08T00:00:00Z");
        }).toList();
        return new PublicGraphSnapshot(4, version, "handoff-" + version, bundle.objects("companies").stream()
                .map(c -> new PublicGraphSnapshot.Company(c.string("id"), c.string("label"), null, null)).toList(),
                issues, visible((ObjectNode) bundle.node()), articles, evidence);
    }
}
