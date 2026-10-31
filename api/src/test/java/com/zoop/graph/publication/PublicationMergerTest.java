package com.zoop.graph.publication;

import java.time.Instant;
import java.util.ArrayList;
import java.util.List;
import java.util.Set;
import com.zoop.common.json.Canonical;
import com.zoop.common.json.StrictJson;
import com.zoop.common.json.StrictJson.Obj;
import com.zoop.document.repository.ArtifactRow;
import com.zoop.graph.publication.GraphPublicationReader.Contribution;
import com.zoop.graph.rules.PublicationRuleEvaluator;
import com.zoop.graph.rules.RuleDefinition;
import com.zoop.graph.snapshot.PublicGraphSnapshot;
import com.zoop.graph.snapshot.PublicGraphSnapshot.Issue;
import org.junit.jupiter.api.Test;
import tools.jackson.databind.node.ObjectNode;
import static org.junit.jupiter.api.Assertions.*;

class PublicationMergerTest {
    @Test
    void preservesOldContributionWhenNewInputOmitsItAndKeepsTwentyOneFlatLeaves() {
        var original = source(0, "issue-0", "A");
        var first = PublicationMerger.merge(List.of(original), PublicationMerger.emptyDecisions(), Set.of());
        List<Contribution> leaves = new ArrayList<>(); leaves.add(original);
        for (int index = 1; index <= 20; index++) leaves.add(source(index, "issue-" + index, "B" + index));
        var next = PublicationMerger.merge(leaves, PublicationMerger.emptyDecisions(), first.issueSources().keySet());
        assertEquals(21, next.issues().size());
        assertEquals(first.issues().getFirst(), next.issues().getFirst());
        assertEquals(Set.copyOf(leaves.stream().map(Contribution::sourceVersionId).toList()), next.issueSources().values().stream()
                .flatMap(o -> o.members().stream()).map(GraphPublicationReader.IssueRef::sourceVersionId).collect(java.util.stream.Collectors.toSet()));
    }

    @Test
    void identicalNewOwnerDoesNotReselectTheBasesHeadlineProof() {
        Contribution first = source(0, "stable", "A"); Contribution second = source(1, "other", "B");
        Contribution base = first.sourceVersionId().compareTo(second.sourceVersionId()) > 0 ? first : second;
        Contribution earlier = base == first ? second : first;
        var p = base.projection();
        var copy = new PublicGraphSnapshot(p.snapshotFormat(), earlier.sourceVersionId(), earlier.sourceId(),
                p.companies(), p.issues(), p.relations(), p.articles(), p.evidence());
        Contribution incoming = new Contribution(earlier.sourceVersionId(), earlier.sourceId(), earlier.sourceKind(),
                earlier.receipt(), earlier.projectionArtifact(), copy, earlier.bundle());
        var old = PublicationMerger.merge(List.of(base), PublicationMerger.emptyDecisions(), Set.of());
        var merged = PublicationMerger.merge(List.of(incoming, base), PublicationMerger.emptyDecisions(),
                old.issueSources().keySet(), old.issueSources());
        String issue = p.issues().getFirst().issueId();
        assertEquals(base.issueRef(issue), merged.issueSources().get(issue).headlineSources().get("label"));
        assertEquals(2, merged.issueSources().get(issue).members().size());
    }

    @Test
    void mergesExactDuplicateFactsAndRefusesConflictingCompanyFacts() {
        Contribution a = source(0, "issue-0", "A");
        Contribution b = source(1, "issue-1", "B");
        assertEquals(1, PublicationMerger.merge(List.of(a, b), PublicationMerger.emptyDecisions(), Set.of()).companies().size());
        var projection = b.projection();
        var changed = new PublicGraphSnapshot(projection.snapshotFormat(), projection.versionId(), projection.sourceBundleId(),
                List.of(new PublicGraphSnapshot.Company("company", "Different catalog fact", null, null)), projection.issues(),
                projection.relations(), projection.articles(), projection.evidence());
        Contribution conflict = new Contribution(b.sourceVersionId(), b.sourceId(), b.sourceKind(), b.receipt(), b.projectionArtifact(), changed, b.bundle());
        assertEquals("identity_conflict", assertThrows(PublicationException.class,
                () -> PublicationMerger.merge(List.of(a, conflict), PublicationMerger.emptyDecisions(), Set.of())).code());
    }

    @Test
    void explicitGroundedMappingKeepsStableIdAndSelectedHeadlines() {
        Contribution a = source(0, "stable", "Original headline");
        Contribution b = source(1, "incoming", "Incoming headline");
        ObjectNode decisions = mapped(a, b);
        var merged = PublicationMerger.merge(List.of(a, b), Obj.of(decisions), Set.of("stable"));
        assertEquals(List.of("stable"), merged.issues().stream().map(Issue::issueId).toList());
        assertEquals("Original headline", merged.issues().getFirst().label());
        assertEquals(2, merged.issueSources().get("stable").members().size());
        assertEquals(Set.of("stable"), merged.relations().stream().map(PublicGraphSnapshot.Relation::source).collect(java.util.stream.Collectors.toSet()));
        assertEquals(a.issueRef("stable"), merged.issueSources().get("stable").headlineSources().get("label"));
        assertEquals("identity_conflict", assertThrows(PublicationException.class,
                () -> PublicationMerger.merge(List.of(a, b), Obj.of(decisions), Set.of("stable", "incoming"))).code());
        ((ObjectNode) decisions.get("issueMappings").get(0)).putArray("evidenceRefs").add(evidenceRef(a));
        assertEquals("mapping_unproven", assertThrows(PublicationException.class,
                () -> PublicationMerger.merge(List.of(a, b), Obj.of(decisions), Set.of("stable"))).code());
    }

    @Test
    void sameIdDisagreementRequiresCorrectionAndCannotUseNewestWins() {
        Contribution a = source(0, "same", "A"); Contribution b = source(1, "same", "B");
        assertEquals("correction_required", assertThrows(PublicationException.class,
                () -> PublicationMerger.merge(List.of(a, b), PublicationMerger.emptyDecisions(), Set.of())).code());
        assertEquals("correction_required", assertThrows(PublicationException.class,
                () -> PublicationMerger.merge(List.of(b, a), PublicationMerger.emptyDecisions(), Set.of())).code());
    }

    @Test
    void retainedRuleFreeContributionCanReappearUnderCurrentRules() {
        Contribution a = source(0, "issue-0", "A"); Contribution b = source(1, "issue-1", "B");
        var first = PublicationMerger.merge(List.of(a), PublicationMerger.emptyDecisions(), Set.of()).snapshot("base", "publication");
        var hidden = PublicationRuleEvaluator.apply(first, List.of(new PublicationRuleEvaluator.EnabledRule("hide@1",
                new RuleDefinition.AssertionStatus(Set.of("occurred"))))).snapshot();
        assertEquals(0, hidden.issues().size());
        var next = PublicationMerger.merge(List.of(a, b), PublicationMerger.emptyDecisions(), Set.of()).snapshot("next", "publication2");
        assertEquals(List.of("issue-0", "issue-1"), PublicationRuleEvaluator.apply(next, List.of()).snapshot().issues().stream().map(Issue::issueId).toList());
    }

    private static ObjectNode mapped(Contribution destination, Contribution incoming) {
        ObjectNode root = (ObjectNode) PublicationMerger.emptyDecisions().node().deepCopy();
        var mapping = ((tools.jackson.databind.node.ArrayNode) root.get("issueMappings")).addObject();
        mapping.set("from", GraphPublicationReader.json(incoming.issueRef(incoming.projection().issues().getFirst().issueId())));
        mapping.set("to", GraphPublicationReader.json(destination.issueRef(destination.projection().issues().getFirst().issueId())));
        mapping.put("decision", "same-event"); mapping.putArray("evidenceRefs").add(evidenceRef(destination)).add(evidenceRef(incoming)); audit(mapping);
        for (String field : List.of("label", "geography")) {
            var choice = ((tools.jackson.databind.node.ArrayNode) root.get("fieldSelections")).addObject();
            var issue = destination.projection().issues().getFirst();
            choice.put("issueId", issue.issueId()); choice.put("field", field);
            choice.put("expectedValueDigest", Canonical.digest(PublicationMerger.field(issue, field)));
            choice.set("takeFrom", GraphPublicationReader.json(destination.issueRef(issue.issueId())));
            choice.putArray("evidenceRefs").add(evidenceRef(destination)); audit(choice);
        }
        return root;
    }
    private static ObjectNode evidenceRef(Contribution source) {
        var node = StrictJson.newObject(); var issue = source.projection().issues().getFirst();
        node.put("sourceVersionId", source.sourceVersionId()); node.put("issueId", issue.issueId()); node.put("evidenceId", issue.evidenceIds().getFirst()); return node;
    }
    private static void audit(ObjectNode node) { node.put("reviewer", "operator"); node.put("decisionRef", "synthetic-review"); node.put("decisionVersion", "1"); }

    static Contribution source(int index, String issueId, String label) {
        String source = "handoff-" + index; String version = "gv-" + Canonical.sha256(source);
        String article = "doc-" + Canonical.sha256("article-" + index); String evidence = "ev-" + Canonical.sha256("evidence-" + index);
        Issue issue = new Issue(issueId, label, null, "unknown", null, "occurred", "action", "target", "domestic", "policy",
                List.of(evidence), List.of(article), List.of(evidence), List.of(), null, "2026-10-01");
        var projection = new PublicGraphSnapshot(3, version, source, List.of(new PublicGraphSnapshot.Company("company", "Company", null, null)),
                List.of(issue), List.of(new PublicGraphSnapshot.Relation("relation-" + index, "INVOLVES", issueId, "company", null, "occurred", List.of(evidence), List.of())),
                List.of(new PublicGraphSnapshot.Article(article, "a".repeat(64), "Article", "https://example.invalid/" + index, "2026-10-01")),
                List.of(new PublicGraphSnapshot.Evidence(evidence, article, "a".repeat(64), 0, 1)));
        ArtifactRow receipt = new ArtifactRow("artifact-receipt-" + version, "verification_receipt", "artifact-root:verification_receipt/" + version + ".json",
                "b".repeat(64), 100, "application/json", Instant.EPOCH);
        ArtifactRow snapshot = new ArtifactRow("artifact-" + version, "graph_snapshot", "artifact-root:graph_snapshot/" + version + ".json",
                "c".repeat(64), 100, "application/json", Instant.EPOCH);
        return new Contribution(version, source, "native", receipt, snapshot, projection, Obj.of(StrictJson.newObject()));
    }
}
