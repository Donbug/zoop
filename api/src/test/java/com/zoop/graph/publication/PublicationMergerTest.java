package com.zoop.graph.publication;

import java.time.Instant;
import java.util.ArrayList;
import java.util.List;
import java.util.Map;
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

    @Test
    void proposalMakesTheNewestIncomingNativeValuePublicAndSurvivesReverification() {
        Contribution published = source(0, "same", "A"); Contribution incoming = source(1, "same", "B");
        var base = PublicationMerger.merge(List.of(published), PublicationMerger.emptyDecisions(), Set.of());
        var prepared = prepare(List.of(published, incoming), PublicationMerger.emptyDecisions(), base, incoming);
        assertEquals("B", prepared.merged().issues().getFirst().label());
        assertEquals(incoming.issueRef("same"), prepared.merged().issueSources().get("same").headlineSources().get("label"));
        var label = prepared.proposal().resolutions().stream().filter(r -> "label".equals(r.field())).findFirst().orElseThrow();
        assertEquals(new PublicationMerger.AutoResolution("issue", "same", "label", incoming.sourceVersionId(), List.of(published.sourceVersionId()),
                Canonical.digest(PublicationMerger.field(published.projection().issues().getFirst(), "label")),
                Canonical.digest(PublicationMerger.field(incoming.projection().issues().getFirst(), "label"))), label);
        assertTrue(prepared.proposal().decisions().objects("fieldSelections").stream()
                .allMatch(d -> PublicationMerger.AUTO_REVIEWER.equals(d.string("reviewer"))));
        // Without the proposal the same inputs still need a decision.
        assertEquals("correction_required", assertThrows(PublicationException.class, () -> PublicationMerger.merge(List.of(published, incoming),
                PublicationMerger.emptyDecisions(), base.issueSources().keySet(), base.issueSources())).code());
    }

    @Test
    void aLaterIncomingReplacesAnEarlierAutomaticDecision() {
        Contribution published = source(0, "same", "A"); Contribution second = source(1, "same", "B"); Contribution third = source(2, "same", "C");
        var base = PublicationMerger.merge(List.of(published), PublicationMerger.emptyDecisions(), Set.of());
        var first = prepare(List.of(published, second), PublicationMerger.emptyDecisions(), base, second);
        var next = prepare(List.of(published, second, third), first.effective(), first.merged(), third);
        assertEquals("C", next.merged().issues().getFirst().label());
        var label = next.proposal().resolutions().stream().filter(r -> "label".equals(r.field())).findFirst().orElseThrow();
        assertEquals(List.of(published.sourceVersionId(), second.sourceVersionId()).stream().sorted().toList(), label.replacedSourceVersionIds());
    }

    @Test
    void noProposalWhenSourcesAdmittedTogetherDisagree() {
        Contribution published = source(0, "same", "A");
        Contribution first = source(1, "same", "B"); Contribution second = source(2, "same", "C");
        var base = PublicationMerger.merge(List.of(published), PublicationMerger.emptyDecisions(), Set.of());
        var all = List.of(published, first, second);
        var proposal = PublicationMerger.propose(all, PublicationMerger.emptyDecisions(), base.issueSources(),
                new PublicationMerger.Automatic(List.of(first.sourceVersionId(), second.sourceVersionId())));
        assertEquals(0, proposal.decisions().objects("fieldSelections").size());
        assertEquals("correction_required", assertThrows(PublicationException.class, () -> PublicationMerger.merge(all,
                PublicationMerger.combine(PublicationMerger.emptyDecisions(), proposal.decisions()), base.issueSources().keySet(), base.issueSources())).code());
        // Parts of a split delivery that carry the same issue with different evidence are the same case.
        Contribution otherPart = source(3, "same", "B");
        assertEquals(0, PublicationMerger.propose(List.of(published, first, otherPart), PublicationMerger.emptyDecisions(), base.issueSources(),
                new PublicationMerger.Automatic(List.of(first.sourceVersionId(), otherPart.sourceVersionId()))).decisions().objects("fieldSelections").size());
    }

    @Test
    void agreeingIncomingSourcesMergeAndTheNewestIsChosen() {
        Contribution published = source(0, "same", "A"); Contribution first = source(1, "same", "B"); Contribution second = copy(first, 2);
        var base = PublicationMerger.merge(List.of(published), PublicationMerger.emptyDecisions(), Set.of());
        var prepared = prepare(List.of(published, first, second), PublicationMerger.emptyDecisions(), base, first, second);
        assertEquals("B", prepared.merged().issues().getFirst().label());
        assertEquals(second.issueRef("same"), prepared.merged().issueSources().get("same").headlineSources().get("label"));
        assertEquals(3, prepared.merged().issueSources().get("same").members().size());
    }

    @Test
    void noProposalForALegacyPackageOrAPeopleDecision() {
        Contribution legacy = legacy(source(0, "same", "A")); Contribution incoming = source(1, "same", "B");
        var legacyBase = PublicationMerger.merge(List.of(legacy), PublicationMerger.emptyDecisions(), Set.of());
        assertEquals(0, PublicationMerger.propose(List.of(legacy, incoming), PublicationMerger.emptyDecisions(), legacyBase.issueSources(),
                new PublicationMerger.Automatic(List.of(incoming.sourceVersionId()))).decisions().objects("fieldSelections").size());

        // A person decided one headline field: the whole issue, and every relation from it, is left to people.
        Contribution published = relation(source(2, "same", "A"), "shared"); Contribution newer = relation(source(3, "same", "B"), "shared");
        var base = PublicationMerger.merge(List.of(published), PublicationMerger.emptyDecisions(), Set.of());
        ObjectNode people = peopleLabel(published);
        var proposal = PublicationMerger.propose(List.of(published, newer), Obj.of(people), base.issueSources(),
                new PublicationMerger.Automatic(List.of(newer.sourceVersionId())));
        assertEquals(0, proposal.decisions().objects("fieldSelections").size());
        assertEquals(0, proposal.decisions().objects("relationSelections").size());
        assertEquals(List.of(), proposal.resolutions());
        // Without an automatic value for geography the operator rule asks for a decision instead of mixing two records.
        assertEquals("correction_required", assertThrows(PublicationException.class, () -> PublicationMerger.merge(List.of(published, newer),
                PublicationMerger.combine(Obj.of(people), proposal.decisions()), base.issueSources().keySet(), base.issueSources())).code());
    }

    @Test
    void anIncomingRecordThatOnlyAddsEvidenceKeepsThePublishedOwner() {
        Contribution published = source(0, "same", "A");
        Contribution incoming = sameHeadline(published, source(1, "same", "A"));
        var base = PublicationMerger.merge(List.of(published), PublicationMerger.emptyDecisions(), Set.of());
        var prepared = prepare(List.of(published, incoming), PublicationMerger.emptyDecisions(), base, incoming);
        var label = prepared.proposal().decisions().objects("fieldSelections");
        assertEquals(1, label.size());
        assertEquals(GraphPublicationReader.json(published.issueRef("same")), label.getFirst().raw("takeFrom"));
        assertEquals(List.of(), prepared.proposal().resolutions());
        var issue = prepared.merged().issues().getFirst();
        assertEquals(base.issues().getFirst().representativeMentionId(), issue.representativeMentionId());
        assertEquals(published.issueRef("same"), prepared.merged().issueSources().get("same").headlineSources().get("label"));
        assertEquals(Set.of(published.projection().issues().getFirst().evidenceIds().getFirst(), incoming.projection().issues().getFirst().evidenceIds().getFirst()),
                Set.copyOf(issue.evidenceIds()));
    }

    @Test
    void onlyThePreparationMayWriteTheAutomaticReviewer() {
        Contribution published = source(0, "same", "A"); Contribution incoming = source(1, "same", "B");
        var base = PublicationMerger.merge(List.of(published), PublicationMerger.emptyDecisions(), Set.of());
        var proposal = PublicationMerger.propose(List.of(published, incoming), PublicationMerger.emptyDecisions(), base.issueSources(),
                new PublicationMerger.Automatic(List.of(incoming.sourceVersionId())));
        assertTrue(PublicationMerger.claimsAutomaticReviewer(proposal.decisions()));
        assertTrue(GraphPublicationConfiguration.claimsAutomaticReviewer(Canonical.bytes(proposal.decisions().node())));
        assertFalse(GraphPublicationConfiguration.claimsAutomaticReviewer(Canonical.bytes(peopleLabel(published))));
        assertFalse(GraphPublicationConfiguration.claimsAutomaticReviewer("not json".getBytes(java.nio.charset.StandardCharsets.UTF_8)));
    }

    @Test
    void proposalTakesTheNewestRelationRecord() {
        Contribution published = relation(source(0, "issue-0", "A"), "shared"); Contribution incoming = relation(source(1, "issue-0", "A"), "shared");
        var base = PublicationMerger.merge(List.of(published), PublicationMerger.emptyDecisions(), Set.of());
        var prepared = prepare(List.of(published, incoming), PublicationMerger.emptyDecisions(), base, incoming);
        var relation = prepared.merged().relations().stream().filter(r -> "shared".equals(r.relationId())).findFirst().orElseThrow();
        assertEquals(incoming.projection().relations().getFirst().evidenceIds(), relation.evidenceIds());
        var reported = prepared.proposal().resolutions().stream().filter(r -> "relation".equals(r.kind())).findFirst().orElseThrow();
        assertEquals("shared", reported.id());
        assertNull(reported.field());
        assertEquals(incoming.sourceVersionId(), reported.sourceVersionId());
        assertEquals(List.of(published.sourceVersionId()), reported.replacedSourceVersionIds());
    }

    @Test
    void aNewIssueNeedsNoProposalAndAnUnknownIncomingSourceIsRefused() {
        Contribution published = source(0, "old", "A"); Contribution incoming = source(1, "new", "B");
        var base = PublicationMerger.merge(List.of(published), PublicationMerger.emptyDecisions(), Set.of());
        var prepared = prepare(List.of(published, incoming), PublicationMerger.emptyDecisions(), base, incoming);
        assertEquals(List.of("new", "old"), prepared.merged().issues().stream().map(Issue::issueId).toList());
        assertEquals(List.of(), prepared.proposal().resolutions());
        assertEquals("request_invalid", assertThrows(PublicationException.class, () -> PublicationMerger.propose(List.of(published),
                PublicationMerger.emptyDecisions(), Map.of(), new PublicationMerger.Automatic(List.of(incoming.sourceVersionId())))).code());
        assertEquals("request_invalid", assertThrows(PublicationException.class, () -> new PublicationMerger.Automatic(List.of())).code());
    }

    @Test
    void operatorFieldSelectionKeepsEveryPartsEvidenceButARelationSelectionKeepsOnlyTheChosenRecord() {
        Contribution a = relation(source(0, "same", "A"), "shared"); Contribution b = relation(source(1, "same", "B"), "shared");
        ObjectNode decisions = (ObjectNode) PublicationMerger.emptyDecisions().node().deepCopy();
        var issue = a.projection().issues().getFirst();
        for (String field : List.of("label", "geography")) {
            var choice = ((tools.jackson.databind.node.ArrayNode) decisions.get("fieldSelections")).addObject();
            choice.put("issueId", "same"); choice.put("field", field);
            choice.put("expectedValueDigest", Canonical.digest(PublicationMerger.field(issue, field)));
            choice.set("takeFrom", GraphPublicationReader.json(a.issueRef("same")));
            choice.putArray("evidenceRefs").add(evidenceRef(a)); audit(choice);
        }
        var relation = ((tools.jackson.databind.node.ArrayNode) decisions.get("relationSelections")).addObject();
        var chosen = a.projection().relations().getFirst();
        relation.put("relationId", "shared");
        relation.put("expectedValueDigest", Canonical.digest(GraphPublicationReader.json(chosen)));
        relation.set("takeFrom", GraphPublicationReader.json(new GraphPublicationReader.RelationRef(a.sourceVersionId(), "shared")));
        relation.putArray("evidenceRefs").add(evidenceRef(a)); audit(relation);
        var merged = PublicationMerger.merge(List.of(a, b), Obj.of(decisions), Set.of());
        assertEquals("A", merged.issues().getFirst().label());
        assertEquals(Set.of(a.projection().issues().getFirst().evidenceIds().getFirst(), b.projection().issues().getFirst().evidenceIds().getFirst()),
                Set.copyOf(merged.issues().getFirst().evidenceIds()));
        assertEquals(chosen.evidenceIds(), merged.relations().getFirst().evidenceIds());
    }

    private record Prepared(PublicationMerger.Proposal proposal, Obj effective, PublicationMerger.Merged merged) {}

    /** Proposes, merges like the composer and re-merges like the reader (stored decisions and owners only). */
    private static Prepared prepare(List<Contribution> all, Obj inherited, PublicationMerger.Merged base, Contribution... incoming) {
        var proposal = PublicationMerger.propose(all, inherited, base.issueSources(),
                new PublicationMerger.Automatic(java.util.Arrays.stream(incoming).map(Contribution::sourceVersionId).toList()));
        // The composer accepts a new decision only when it names the value published before (GraphPublicationComposer.compose).
        for (Obj choice : proposal.decisions().objects("fieldSelections")) {
            var previous = base.issues().stream().filter(i -> i.issueId().equals(choice.string("issueId"))).findFirst();
            previous.ifPresent(p -> assertEquals(Canonical.digest(PublicationMerger.field(p, choice.string("field"))), choice.string("expectedValueDigest")));
        }
        for (Obj choice : proposal.decisions().objects("relationSelections")) {
            var previous = base.relations().stream().filter(r -> r.relationId().equals(choice.string("relationId"))).findFirst();
            previous.ifPresent(p -> assertEquals(Canonical.digest(GraphPublicationReader.json(p)), choice.string("expectedValueDigest")));
        }
        Obj effective = PublicationMerger.combine(inherited, proposal.decisions());
        var merged = PublicationMerger.merge(all, effective, base.issueSources().keySet(), base.issueSources());
        var reread = PublicationMerger.merge(all, effective, Set.of(), merged.issueSources());
        assertEquals(merged.issues(), reread.issues());
        assertEquals(merged.relations(), reread.relations());
        assertEquals(merged.issueSources(), reread.issueSources());
        return new Prepared(proposal, effective, merged);
    }

    private static ObjectNode peopleLabel(Contribution published) {
        ObjectNode people = (ObjectNode) PublicationMerger.emptyDecisions().node().deepCopy();
        var choice = ((tools.jackson.databind.node.ArrayNode) people.get("fieldSelections")).addObject();
        choice.put("issueId", "same"); choice.put("field", "label");
        choice.put("expectedValueDigest", Canonical.digest(PublicationMerger.field(published.projection().issues().getFirst(), "label")));
        choice.set("takeFrom", GraphPublicationReader.json(published.issueRef("same")));
        choice.putArray("evidenceRefs").add(evidenceRef(published)); audit(choice);
        return people;
    }
    /** {@code other}'s source and evidence, with every headline field of {@code published}'s issue. */
    private static Contribution sameHeadline(Contribution published, Contribution other) {
        Issue p = published.projection().issues().getFirst(); Issue o = other.projection().issues().getFirst();
        Issue issue = new Issue(p.issueId(), p.label(), p.eventTime(), p.timePrecision(), p.period(), p.assertionStatus(), p.action(), p.target(),
                p.geography(), p.geographyPolicyVersion(), p.geographyEvidenceIds(), o.articleIds(), o.evidenceIds(), p.mentions(),
                p.representativeMentionId(), p.latestPublishedAt());
        var x = other.projection();
        var projection = new PublicGraphSnapshot(x.snapshotFormat(), x.versionId(), x.sourceBundleId(), x.companies(), List.of(issue),
                x.relations(), x.articles(), x.evidence());
        return new Contribution(other.sourceVersionId(), other.sourceId(), other.sourceKind(), other.receipt(), other.projectionArtifact(),
                projection, other.bundle());
    }
    private static Contribution copy(Contribution original, int index) {
        String source = "handoff-" + index; String version = "gv-" + Canonical.sha256(source); var p = original.projection();
        var projection = new PublicGraphSnapshot(p.snapshotFormat(), version, source, p.companies(), p.issues(), p.relations(), p.articles(), p.evidence());
        return new Contribution(version, source, original.sourceKind(), original.receipt(), original.projectionArtifact(), projection, original.bundle());
    }
    private static Contribution legacy(Contribution original) {
        return new Contribution(original.sourceVersionId(), original.sourceId(), "legacy-real", original.receipt(), original.projectionArtifact(),
                original.projection(), original.bundle());
    }
    private static Contribution relation(Contribution original, String relationId) {
        var p = original.projection(); var r = p.relations().getFirst();
        var renamed = new PublicGraphSnapshot.Relation(relationId, r.relationType(), r.source(), r.target(), r.role(), r.assertionStatus(), r.evidenceIds(), r.basis());
        var projection = new PublicGraphSnapshot(p.snapshotFormat(), p.versionId(), p.sourceBundleId(), p.companies(), p.issues(), List.of(renamed), p.articles(), p.evidence());
        return new Contribution(original.sourceVersionId(), original.sourceId(), original.sourceKind(), original.receipt(), original.projectionArtifact(),
                projection, original.bundle());
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
