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
    void aChangedHeadlineValueIsReportedAndLeftToPeople() {
        Contribution published = source(0, "same", "A"); Contribution incoming = source(1, "same", "B");
        var base = PublicationMerger.merge(List.of(published), PublicationMerger.emptyDecisions(), Set.of());
        var proposal = propose(List.of(published, incoming), PublicationMerger.emptyDecisions(), base, incoming);
        assertEquals(0, proposal.decisions().objects("fieldSelections").size());
        assertEquals(0, proposal.decisions().objects("relationSelections").size());
        assertEquals(List.of(), proposal.sameHeadlines());
        var label = proposal.changes().stream().filter(c -> "label".equals(c.field())).findFirst().orElseThrow();
        assertEquals("issue", label.kind());
        assertEquals("same", label.id());
        assertEquals(Set.of(
                new PublicationMerger.SourceValue(published.sourceVersionId(), "base",
                        Canonical.digest(PublicationMerger.field(published.projection().issues().getFirst(), "label"))),
                new PublicationMerger.SourceValue(incoming.sourceVersionId(), "incoming",
                        Canonical.digest(PublicationMerger.field(incoming.projection().issues().getFirst(), "label")))),
                Set.copyOf(label.values()));
        // Nothing is chosen, so the composer stops for a person.
        assertEquals("correction_required", assertThrows(PublicationException.class, () -> PublicationMerger.merge(List.of(published, incoming),
                PublicationMerger.combine(PublicationMerger.emptyDecisions(), proposal.decisions()), base.issueSources().keySet(), base.issueSources())).code());
    }

    @Test
    void aChangedRelationRecordIsReportedAndLeftToPeople() {
        Contribution published = relation(source(0, "same", "A"), "shared");
        Contribution incoming = relation(sameHeadline(published, source(1, "same", "A")), "shared");
        var base = PublicationMerger.merge(List.of(published), PublicationMerger.emptyDecisions(), Set.of());
        var proposal = propose(List.of(published, incoming), PublicationMerger.emptyDecisions(), base, incoming);
        assertEquals(0, proposal.decisions().objects("relationSelections").size());
        var change = proposal.changes().stream().filter(c -> "relation".equals(c.kind())).findFirst().orElseThrow();
        assertEquals("shared", change.id());
        assertNull(change.field());
        assertEquals(Set.of("base", "incoming"), change.values().stream().map(PublicationMerger.SourceValue::side).collect(java.util.stream.Collectors.toSet()));
        // The issue itself only gained evidence, so it would merge; the relation still stops the composition.
        assertEquals(1, proposal.sameHeadlines().size());
        assertEquals("correction_required", assertThrows(PublicationException.class, () -> PublicationMerger.merge(List.of(published, incoming),
                PublicationMerger.combine(PublicationMerger.emptyDecisions(), proposal.decisions()), base.issueSources().keySet(), base.issueSources())).code());
    }

    @Test
    void sourcesAdmittedTogetherThatDisagreeAreReportedWithTheirSides() {
        Contribution published = source(0, "same", "A");
        Contribution first = source(1, "same", "B"); Contribution second = source(2, "same", "C");
        var base = PublicationMerger.merge(List.of(published), PublicationMerger.emptyDecisions(), Set.of());
        var proposal = propose(List.of(published, first, second), PublicationMerger.emptyDecisions(), base, first, second);
        assertEquals(0, proposal.decisions().objects("fieldSelections").size());
        var label = proposal.changes().stream().filter(c -> "label".equals(c.field())).findFirst().orElseThrow();
        assertEquals(3, label.values().size());
        assertEquals(2, label.values().stream().filter(v -> "incoming".equals(v.side())).count());
        assertEquals("correction_required", assertThrows(PublicationException.class, () -> PublicationMerger.merge(List.of(published, first, second),
                PublicationMerger.combine(PublicationMerger.emptyDecisions(), proposal.decisions()), base.issueSources().keySet(), base.issueSources())).code());
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
        assertEquals("graph-publication-prepare:same-headline", label.getFirst().string("decisionRef"));
        assertEquals(List.of(), prepared.proposal().changes());
        var issue = prepared.merged().issues().getFirst();
        assertEquals(base.issues().getFirst().representativeMentionId(), issue.representativeMentionId());
        assertEquals(List.of(new PublicationMerger.SameHeadline("same", published.sourceVersionId(),
                base.issues().getFirst().representativeMentionId(), issue.representativeMentionId())), prepared.proposal().sameHeadlines());
        assertEquals(published.issueRef("same"), prepared.merged().issueSources().get("same").headlineSources().get("label"));
        assertEquals(Set.of(published.projection().issues().getFirst().evidenceIds().getFirst(), incoming.projection().issues().getFirst().evidenceIds().getFirst()),
                Set.copyOf(issue.evidenceIds()));
        // The next preparation keeps the stored decision: nothing is replaced.
        Contribution later = sameHeadline(published, source(2, "same", "A"));
        var next = prepare(List.of(published, incoming, later), prepared.effective(), prepared.merged(), later);
        assertEquals(0, next.proposal().decisions().objects("fieldSelections").size());
        assertEquals(published.issueRef("same"), next.merged().issueSources().get("same").headlineSources().get("label"));
    }

    @Test
    void aLaterHeadlineChangeIsNotHiddenByAnEarlierAutomaticSelection() {
        Contribution published = source(0, "same", "A");
        Contribution incoming = sameHeadline(published, source(1, "same", "A"));
        var base = PublicationMerger.merge(List.of(published), PublicationMerger.emptyDecisions(), Set.of());
        var prepared = prepare(List.of(published, incoming), PublicationMerger.emptyDecisions(), base, incoming);
        assertEquals(1, prepared.proposal().decisions().objects("fieldSelections").size());

        // The next source changes only the headline label: it is reported and stops, the stored automatic selection decides nothing.
        Contribution retitled = relabel(sameHeadline(published, source(2, "same", "A")), "다른 제목");
        var all = List.of(published, incoming, retitled);
        var next = propose(all, prepared.effective(), prepared.merged(), retitled);
        assertEquals(0, next.decisions().objects("fieldSelections").size());
        var label = next.changes().stream().filter(c -> "label".equals(c.field())).findFirst().orElseThrow();
        assertEquals(List.of(retitled.sourceVersionId()), label.values().stream().filter(v -> "incoming".equals(v.side()))
                .map(PublicationMerger.SourceValue::sourceVersionId).toList());
        assertEquals("correction_required", assertThrows(PublicationException.class, () -> PublicationMerger.merge(all,
                PublicationMerger.combine(prepared.effective(), next.decisions()), prepared.merged().issueSources().keySet(),
                prepared.merged().issueSources())).code());

        // A person's selection replaces the automatic one under the same key and settles the label.
        var decided = PublicationMerger.merge(all, PublicationMerger.combine(prepared.effective(), Obj.of(peopleLabel(published))),
                prepared.merged().issueSources().keySet(), prepared.merged().issueSources());
        assertEquals(published.projection().issues().getFirst().label(), decided.issues().getFirst().label());
    }

    @Test
    void identicalIncomingRecordsMergeWithoutADecision() {
        Contribution published = source(0, "same", "A"); Contribution first = copy(published, 1); Contribution second = copy(published, 2);
        var base = PublicationMerger.merge(List.of(published), PublicationMerger.emptyDecisions(), Set.of());
        var prepared = prepare(List.of(published, first, second), PublicationMerger.emptyDecisions(), base, first, second);
        assertEquals(0, prepared.proposal().decisions().objects("fieldSelections").size());
        assertEquals(List.of(), prepared.proposal().changes());
        assertEquals(3, prepared.merged().issueSources().get("same").members().size());
    }

    @Test
    void noProposalForALegacyPackageOrAPeopleDecision() {
        Contribution legacy = legacy(source(0, "same", "A")); Contribution incoming = sameHeadline(legacy, source(1, "same", "A"));
        var legacyBase = PublicationMerger.merge(List.of(legacy), PublicationMerger.emptyDecisions(), Set.of());
        assertEquals(0, propose(List.of(legacy, incoming), PublicationMerger.emptyDecisions(), legacyBase, incoming)
                .decisions().objects("fieldSelections").size());
        // A legacy group whose value changed is reported and stops like any other.
        Contribution changed = source(4, "same", "B");
        var legacyChange = propose(List.of(legacy, changed), PublicationMerger.emptyDecisions(), legacyBase, changed);
        assertEquals(0, legacyChange.decisions().objects("fieldSelections").size());
        assertTrue(legacyChange.changes().stream().anyMatch(c -> "label".equals(c.field())));
        assertEquals("correction_required", assertThrows(PublicationException.class, () -> PublicationMerger.merge(List.of(legacy, changed),
                PublicationMerger.combine(PublicationMerger.emptyDecisions(), legacyChange.decisions()), legacyBase.issueSources().keySet(),
                legacyBase.issueSources())).code());

        // A person decided the label: that field is covered and the issue gets no automatic decision.
        Contribution published = source(2, "same", "A"); Contribution newer = source(3, "same", "B");
        var base = PublicationMerger.merge(List.of(published), PublicationMerger.emptyDecisions(), Set.of());
        var proposal = propose(List.of(published, newer), Obj.of(peopleLabel(published)), base, newer);
        assertEquals(0, proposal.decisions().objects("fieldSelections").size());
        assertTrue(proposal.changes().stream().noneMatch(c -> "label".equals(c.field())));
        assertTrue(proposal.changes().stream().anyMatch(c -> "geography".equals(c.field())));

        // The inherited decision (a first47-style decisions file) keeps the person's owner when a later source only adds evidence.
        Contribution later = sameHeadline(published, source(5, "same", "A"));
        var kept = prepare(List.of(published, later), Obj.of(peopleLabel(published)), base, later);
        assertEquals(0, kept.proposal().decisions().objects("fieldSelections").size());
        assertEquals(published.issueRef("same"), kept.merged().issueSources().get("same").headlineSources().get("label"));
        assertFalse(PublicationMerger.claimsAutomaticReviewer(kept.effective()));
    }

    @Test
    void aNewIssueNeedsNoProposalAndAnUnknownIncomingSourceIsRefused() {
        Contribution published = source(0, "old", "A"); Contribution incoming = source(1, "new", "B");
        var base = PublicationMerger.merge(List.of(published), PublicationMerger.emptyDecisions(), Set.of());
        var prepared = prepare(List.of(published, incoming), PublicationMerger.emptyDecisions(), base, incoming);
        assertEquals(List.of("new", "old"), prepared.merged().issues().stream().map(Issue::issueId).toList());
        assertEquals(List.of(), prepared.proposal().changes());
        assertEquals(List.of(), prepared.proposal().sameHeadlines());
        assertEquals("request_invalid", assertThrows(PublicationException.class, () -> PublicationMerger.propose(List.of(published),
                PublicationMerger.emptyDecisions(), Map.of(), new PublicationMerger.Automatic(List.of(incoming.sourceVersionId())))).code());
        assertEquals("request_invalid", assertThrows(PublicationException.class, () -> new PublicationMerger.Automatic(List.of())).code());
    }

    @Test
    void onlyThePreparationMayWriteTheAutomaticReviewer() {
        Contribution published = source(0, "same", "A"); Contribution incoming = sameHeadline(published, source(1, "same", "A"));
        var base = PublicationMerger.merge(List.of(published), PublicationMerger.emptyDecisions(), Set.of());
        var proposal = propose(List.of(published, incoming), PublicationMerger.emptyDecisions(), base, incoming);
        assertTrue(PublicationMerger.claimsAutomaticReviewer(proposal.decisions()));
        assertTrue(GraphPublicationPreparer.claimsAutomaticReviewer(Canonical.bytes(proposal.decisions().node())));
        assertFalse(GraphPublicationPreparer.claimsAutomaticReviewer(Canonical.bytes(peopleLabel(published))));
        assertFalse(GraphPublicationPreparer.claimsAutomaticReviewer("not json".getBytes(java.nio.charset.StandardCharsets.UTF_8)));
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

    @Test
    void aLabelCorrectionReplacesOnlyTheNameAndIsReproducedOnRead() {
        Contribution published = source(0, "same", "Article headline");
        var base = PublicationMerger.merge(List.of(published), PublicationMerger.emptyDecisions(), Set.of());
        Obj effective = PublicationMerger.combine(PublicationMerger.emptyDecisions(), Obj.of(corrected(published, "Corrected name")));
        assertEquals(PublicationMerger.DECISIONS_SCHEMA_2, effective.string("schemaVersion"));
        var merged = PublicationMerger.merge(List.of(published), effective, base.issueSources().keySet(), base.issueSources());
        Issue before = base.issues().getFirst(); Issue after = merged.issues().getFirst();
        assertEquals("Corrected name", after.label());
        ObjectNode expected = (ObjectNode) GraphPublicationReader.json(before); expected.put("label", "Corrected name");
        assertEquals(expected, GraphPublicationReader.json(after));
        assertEquals(base.issueSources(), merged.issueSources());
        assertEquals(base.relations(), merged.relations());
        // The reader re-merges from the stored decisions and owners only.
        var reread = PublicationMerger.merge(List.of(published), effective, Set.of(), merged.issueSources());
        assertEquals(merged.issues(), reread.issues());
        assertEquals(merged.issueSources(), reread.issueSources());
        assertEquals(1, PublicationMerger.labelCorrections(effective).size());
        assertEquals(0, PublicationMerger.labelCorrections(PublicationMerger.emptyDecisions()).size());
        assertFalse(PublicationMerger.claimsAutomaticReviewer(effective));
        // Without a correction the combined document keeps the first schema, as every stored publication wrote it.
        var plain = PublicationMerger.combine(PublicationMerger.emptyDecisions(), Obj.of(peopleLabel(published)));
        assertEquals(PublicationMerger.DECISIONS_SCHEMA, plain.string("schemaVersion"));
        assertFalse(plain.has(PublicationMerger.LABEL_CORRECTIONS));
    }

    @Test
    void aLabelCorrectionNamesTheSourceValueItCorrectsAndStopsWhenASourceChangesIt() {
        Contribution published = source(0, "same", "Article headline");
        var base = PublicationMerger.merge(List.of(published), PublicationMerger.emptyDecisions(), Set.of());
        Obj effective = PublicationMerger.combine(PublicationMerger.emptyDecisions(), Obj.of(corrected(published, "Corrected name")));
        ObjectNode wrong = corrected(published, "Corrected name");
        correction(wrong).put("expectedLabelDigest", "0".repeat(64));
        assertEquals("identity_conflict", code(() -> PublicationMerger.merge(List.of(published), Obj.of(wrong), Set.of())));
        // A later source changes the headline: nothing selected it, so the merge stops instead of carrying the old name forward.
        Contribution changed = relabel(copy(published, 1), "Changed headline");
        assertEquals("correction_required", code(() -> PublicationMerger.merge(List.of(published, changed), effective,
                base.issueSources().keySet(), base.issueSources())));
        var proposal = propose(List.of(published, changed), effective, base, changed);
        assertEquals(0, proposal.decisions().objects("fieldSelections").size());
        assertTrue(proposal.changes().stream().anyMatch(c -> "label".equals(c.field())));
        // A person selects the changed value: the correction names the value before it, so it is refused and must be decided again.
        Obj selected = PublicationMerger.combine(effective, Obj.of(peopleLabel(changed)));
        assertEquals("identity_conflict", code(() -> PublicationMerger.merge(List.of(published, changed), selected,
                base.issueSources().keySet(), base.issueSources())));
        // Selecting the published value keeps the correction.
        Obj kept = PublicationMerger.combine(effective, Obj.of(peopleLabel(published)));
        var merged = PublicationMerger.merge(List.of(published, changed), kept, base.issueSources().keySet(), base.issueSources());
        assertEquals("Corrected name", merged.issues().getFirst().label());
        assertEquals(published.issueRef("same"), merged.issueSources().get("same").headlineSources().get("label"));
    }

    @Test
    void aLabelCorrectionIsRefusedWhenUnusedDuplicateUngroundedAutomaticOrNotAName() {
        Contribution published = source(0, "same", "Article headline"); Contribution other = source(1, "other", "Other");
        ObjectNode unknown = corrected(published, "Name"); correction(unknown).put("issueId", "missing");
        assertEquals("mapping_unproven", code(() -> PublicationMerger.merge(List.of(published), Obj.of(unknown), Set.of())));
        ObjectNode duplicate = corrected(published, "Name");
        ((tools.jackson.databind.node.ArrayNode) duplicate.get(PublicationMerger.LABEL_CORRECTIONS)).add(correction(duplicate).deepCopy());
        assertEquals("request_invalid", code(() -> PublicationMerger.merge(List.of(published), Obj.of(duplicate), Set.of())));
        assertEquals("request_invalid", code(() -> PublicationMerger.combine(PublicationMerger.emptyDecisions(), Obj.of(duplicate))));
        ObjectNode foreign = corrected(published, "Name"); correction(foreign).putArray("evidenceRefs").add(evidenceRef(other));
        assertEquals("mapping_unproven", code(() -> PublicationMerger.merge(List.of(published, other), Obj.of(foreign), Set.of())));
        // Evidence of another member of the same issue is refused too: only the label owner's evidence, the issue's atomic proof, counts.
        var base = PublicationMerger.merge(List.of(published), PublicationMerger.emptyDecisions(), Set.of());
        Contribution member = sameHeadline(published, source(2, "same", "Article headline"));
        ObjectNode nonOwner = corrected(published, "Name"); correction(nonOwner).putArray("evidenceRefs").add(evidenceRef(member));
        Obj withSelection = PublicationMerger.combine(Obj.of(peopleLabel(published)), Obj.of(nonOwner));
        assertEquals("mapping_unproven", code(() -> PublicationMerger.merge(List.of(published, member), withSelection, base.issueSources().keySet(), base.issueSources())));
        Obj ownerOnly = PublicationMerger.combine(Obj.of(peopleLabel(published)), Obj.of(corrected(published, "Name")));
        assertEquals("Name", PublicationMerger.merge(List.of(published, member), ownerOnly, base.issueSources().keySet(), base.issueSources()).issues().getFirst().label());
        ObjectNode mixed = corrected(published, "Name"); ((tools.jackson.databind.node.ArrayNode) correction(mixed).get("evidenceRefs")).add(evidenceRef(member));
        Obj both = PublicationMerger.combine(Obj.of(peopleLabel(published)), Obj.of(mixed));
        assertEquals("mapping_unproven", code(() -> PublicationMerger.merge(List.of(published, member), both, base.issueSources().keySet(), base.issueSources())));
        // A selection that moves the owner to a member with the same text leaves a carried correction ungrounded until it is restated.
        Obj moved = PublicationMerger.combine(Obj.of(corrected(published, "Name")), Obj.of(peopleLabelOf(member)));
        assertEquals("mapping_unproven", code(() -> PublicationMerger.merge(List.of(published, member), moved, base.issueSources().keySet(), base.issueSources())));
        ObjectNode restated = corrected(member, "Name");
        Obj regrounded = PublicationMerger.combine(moved, Obj.of(restated));
        var movedMerge = PublicationMerger.merge(List.of(published, member), regrounded, base.issueSources().keySet(), base.issueSources());
        assertEquals("Name", movedMerge.issues().getFirst().label());
        assertEquals(member.issueRef("same"), movedMerge.issueSources().get("same").headlineSources().get("label"));
        // Without a base the owner is the default one (the member carrying the public id first in source order): only its evidence counts.
        Contribution twin = copy(published, 3);
        Contribution earlier = published.sourceVersionId().compareTo(twin.sourceVersionId()) < 0 ? published : twin;
        Contribution later = earlier == published ? twin : published;
        assertEquals("Name", PublicationMerger.merge(List.of(published, twin), Obj.of(corrected(earlier, "Name")), Set.of()).issues().getFirst().label());
        assertEquals("mapping_unproven", code(() -> PublicationMerger.merge(List.of(published, twin), Obj.of(corrected(later, "Name")), Set.of())));
        // Invisible code points are refused like control characters: zero-width space, bidi override, line separator, lone surrogate.
        for (String bad : List.of("Name​", "삼성전자‮담합", "Na me", "Na\uD83Dme", "Name")) {
            ObjectNode name = corrected(published, bad);
            assertEquals("request_invalid", code(() -> PublicationMerger.merge(List.of(published), Obj.of(name), Set.of())), bad);
        }
        assertEquals("삼성전자·ASML, High NA EUV 도입 협력 계획 😀", PublicationMerger.merge(List.of(published),
                Obj.of(corrected(published, "삼성전자·ASML, High NA EUV 도입 협력 계획 😀")), Set.of()).issues().getFirst().label());
        assertEquals("High NA EUV", PublicationMerger.merge(List.of(published), Obj.of(corrected(published, "High NA EUV")), Set.of()).issues().getFirst().label());
        ObjectNode automatic = corrected(published, "Name"); correction(automatic).put("reviewer", PublicationMerger.AUTO_REVIEWER);
        assertTrue(PublicationMerger.claimsAutomaticReviewer(Obj.of(automatic)));
        assertEquals("request_invalid", code(() -> PublicationMerger.merge(List.of(published), Obj.of(automatic), Set.of())));
        // The length limit counts code points: a name of MAX_LABEL_LENGTH supplementary characters is 2 × MAX UTF-16 units and passes.
        String supplementary = "😀".repeat(PublicationMerger.MAX_LABEL_LENGTH);
        assertEquals(supplementary, PublicationMerger.merge(List.of(published), Obj.of(corrected(published, supplementary)), Set.of()).issues().getFirst().label());
        // Blank or padded names include the no-break spaces String.isBlank/strip ignore (U+00A0, U+202F); an inner no-break space is text.
        for (String bad : List.of("", " ", " Name", "Name ", " ", "  ", " Name", "Name ", "Na\u0007me",
                "n".repeat(PublicationMerger.MAX_LABEL_LENGTH + 1))) {
            ObjectNode name = corrected(published, bad);
            assertEquals("request_invalid", code(() -> PublicationMerger.merge(List.of(published), Obj.of(name), Set.of())), bad);
        }
        String longest = "n".repeat(PublicationMerger.MAX_LABEL_LENGTH);
        assertEquals(longest, PublicationMerger.merge(List.of(published), Obj.of(corrected(published, longest)), Set.of()).issues().getFirst().label());
        // Correcting back to the source name withdraws the display change; the decision stays on record.
        Obj withdrawn = PublicationMerger.combine(Obj.of(corrected(published, "Name")), Obj.of(corrected(published, "Article headline")));
        assertEquals(1, PublicationMerger.labelCorrections(withdrawn).size());
        assertEquals("Article headline", PublicationMerger.merge(List.of(published), withdrawn, Set.of()).issues().getFirst().label());
        ObjectNode first = corrected(published, "Name"); first.put("schemaVersion", PublicationMerger.DECISIONS_SCHEMA);
        assertEquals("request_invalid", code(() -> PublicationMerger.merge(List.of(published), Obj.of(first), Set.of())));
        ObjectNode extra = corrected(published, "Name"); extra.putArray("other");
        assertEquals("request_invalid", code(() -> PublicationMerger.merge(List.of(published), Obj.of(extra), Set.of())));
        ObjectNode partial = corrected(published, "Name"); correction(partial).remove("evidenceRefs");
        assertEquals("request_invalid", code(() -> PublicationMerger.merge(List.of(published), Obj.of(partial), Set.of())));
    }

    @Test
    void aCorrectedIssueTakesTheSameHeadlineSelectionAndALaterCorrectionReplacesTheEarlierOne() {
        Contribution published = source(0, "same", "Article headline");
        var base = PublicationMerger.merge(List.of(published), PublicationMerger.emptyDecisions(), Set.of());
        Obj inherited = PublicationMerger.combine(PublicationMerger.emptyDecisions(), Obj.of(corrected(published, "Corrected name")));
        var corrected = PublicationMerger.merge(List.of(published), inherited, base.issueSources().keySet(), base.issueSources());
        // A source that only adds evidence: the usual same-headline selection keeps the owner (its digest is the owner's source value,
        // not the corrected name) and the corrected name is inherited on top of it.
        Contribution incoming = sameHeadline(published, source(1, "same", "Article headline"));
        var prepared = prepare(List.of(published, incoming), inherited, corrected, incoming);
        var selections = prepared.proposal().decisions().objects("fieldSelections");
        assertEquals(1, selections.size());
        assertEquals(Canonical.digest(PublicationMerger.field(published.projection().issues().getFirst(), "label")), selections.getFirst().string("expectedValueDigest"));
        assertEquals(1, prepared.proposal().sameHeadlines().size());
        assertEquals(List.of(), prepared.proposal().changes());
        assertEquals(PublicationMerger.DECISIONS_SCHEMA, prepared.proposal().decisions().string("schemaVersion"));
        assertEquals(PublicationMerger.DECISIONS_SCHEMA_2, prepared.effective().string("schemaVersion"));
        assertEquals("Corrected name", prepared.merged().issues().getFirst().label());
        assertEquals(published.issueRef("same"), prepared.merged().issueSources().get("same").headlineSources().get("label"));
        assertEquals(2, prepared.merged().issues().getFirst().evidenceIds().size());
        // A later correction of the same issue replaces the earlier one; the digest still names the source value.
        Obj replaced = PublicationMerger.combine(prepared.effective(), Obj.of(corrected(published, "Second name")));
        assertEquals(1, PublicationMerger.labelCorrections(replaced).size());
        assertEquals("Second name", PublicationMerger.merge(List.of(published, incoming), replaced, Set.of(), prepared.merged().issueSources())
                .issues().getFirst().label());
    }

    /** The failure code a merge or combine reports: a malformed document is the composer's {@code request_invalid}. */
    @Test
    void scopeDecisionsHaveTheirOwnSchemaAndCombineToTheLowestOne() {
        Contribution published = source(0, "same", "A"); Contribution incoming = sameHeadline(published, source(1, "same", "A"));
        List<Contribution> all = List.of(published, incoming);
        var combined = PublicationMerger.combine(PublicationMerger.emptyDecisions(), Obj.of(exclude(scoped(), "same", incoming, "excluded")));
        assertEquals(PublicationMerger.DECISIONS_SCHEMA_3, combined.string("schemaVersion"));
        assertEquals(1, PublicationMerger.memberExclusions(combined).size());
        assertEquals(Set.of(incoming.issueRef("same")), PublicationMerger.effective(combined).excludedMembers());
        // The same key again replaces the record: its status is the decision in force, and the record keeps the document at -3.
        var restored = PublicationMerger.combine(combined, Obj.of(exclude(scoped(), "same", incoming, "restored")));
        assertEquals(PublicationMerger.DECISIONS_SCHEMA_3, restored.string("schemaVersion"));
        assertEquals(List.of("restored"), PublicationMerger.memberExclusions(restored).stream().map(o -> o.string("status")).toList());
        assertEquals(Set.of(), PublicationMerger.effective(restored).excludedMembers());
        // The same status with other audit fields is a new record that replaces the old one whole: the combined document differs
        // from the previous one (so an empty-incoming compose makes a candidate), while the identical record leaves it equal.
        ObjectNode reaudited = exclude(scoped(), "same", incoming, "excluded");
        ((ObjectNode) reaudited.get(PublicationMerger.MEMBER_EXCLUSIONS).get(0)).put("decisionRef", "scope-review-2");
        assertNotEquals(combined.node(), PublicationMerger.combine(combined, Obj.of(reaudited)).node());
        assertEquals(combined.node(), PublicationMerger.combine(combined, Obj.of(exclude(scoped(), "same", incoming, "excluded"))).node());
        // Without a scope record the lowest schema is recorded: -2 with a correction, -1 otherwise.
        assertEquals(PublicationMerger.DECISIONS_SCHEMA_2, PublicationMerger.combine(PublicationMerger.emptyDecisions(), Obj.of(corrected(published, "이름"))).string("schemaVersion"));
        assertEquals(PublicationMerger.DECISIONS_SCHEMA, PublicationMerger.combine(Obj.of(scoped()), PublicationMerger.emptyDecisions()).string("schemaVersion"));
        // -3 is closed over six arrays; an unknown status, a duplicate key in one file or the automatic reviewer is refused.
        ObjectNode missing = scoped(); missing.remove(PublicationMerger.ISSUE_RETIREMENTS);
        assertEquals("request_invalid", code(() -> PublicationMerger.combine(PublicationMerger.emptyDecisions(), Obj.of(missing))));
        assertEquals("request_invalid", code(() -> PublicationMerger.merge(all, Obj.of(exclude(scoped(), "same", incoming, "gone")), Set.of())));
        assertEquals("request_invalid", code(() -> PublicationMerger.merge(all, Obj.of(retire(scoped(), "same", "excluded")), Set.of())));
        ObjectNode twice = exclude(exclude(scoped(), "same", incoming, "excluded"), "same", incoming, "restored");
        assertEquals("request_invalid", code(() -> PublicationMerger.combine(PublicationMerger.emptyDecisions(), Obj.of(twice))));
        assertEquals("request_invalid", code(() -> PublicationMerger.merge(all, Obj.of(twice), Set.of())));
        ObjectNode automatic = exclude(scoped(), "same", incoming, "excluded");
        ((ObjectNode) automatic.get(PublicationMerger.MEMBER_EXCLUSIONS).get(0)).put("reviewer", PublicationMerger.AUTO_REVIEWER);
        assertTrue(PublicationMerger.claimsAutomaticReviewer(Obj.of(automatic)));
        assertEquals("request_invalid", code(() -> PublicationMerger.merge(all, Obj.of(automatic), Set.of())));
    }

    @Test
    void anExcludedMemberLeavesTheUnionAndItsProofButNotTheOwnersValues() {
        Contribution published = source(0, "same", "A"); Contribution incoming = sameHeadline(published, source(1, "same", "A"));
        List<Contribution> all = List.of(published, incoming);
        var base = PublicationMerger.merge(List.of(published), PublicationMerger.emptyDecisions(), Set.of());
        // Two records that differ only in evidence merge under the owner's label selection (what the preparation proposes).
        var both = PublicationMerger.merge(all, labelOnly(published), base.issueSources().keySet(), base.issueSources());
        assertEquals(2, both.issueSources().get("same").members().size());
        assertEquals(2, both.evidence().size());
        Obj decisions = Obj.of(selectLabel(exclude(scoped(), "same", incoming, "excluded"), published));
        var merged = PublicationMerger.merge(all, decisions, base.issueSources().keySet(), base.issueSources());
        // The union is the owner's alone again; the headline values never depended on the excluded member.
        assertEquals(base.issues().getFirst(), merged.issues().getFirst());
        assertEquals(List.of(published.issueRef("same")), merged.issueSources().get("same").members());
        assertEquals(base.issueSources().get("same").headlineSources(), merged.issueSources().get("same").headlineSources());
        assertEquals(1, merged.memberExclusions()); assertEquals(0, merged.issueRetirements());
        // Its own article, evidence and INVOLVES record leave the snapshot; the owner's stay.
        assertEquals(base.articles(), merged.articles()); assertEquals(base.evidence(), merged.evidence());
        assertEquals(List.of("relation-0"), merged.relations().stream().map(PublicGraphSnapshot.Relation::relationId).toList());
        assertEquals(Set.of("relation-0"), merged.relationSources().keySet());
        // The reader reproduces it from the stored owners, which list the valid members only.
        assertEquals(merged, PublicationMerger.merge(all, decisions, Set.of(), merged.issueSources()));
        // Later compositions inherit it; a third source's member of the issue is another member and merges by default.
        Contribution third = sameHeadline(published, source(2, "same", "A"));
        var inherited = PublicationMerger.merge(List.of(published, incoming, third), PublicationMerger.combine(decisions, PublicationMerger.emptyDecisions()),
                merged.issueSources().keySet(), merged.issueSources());
        assertEquals(Set.of(published.issueRef("same"), third.issueRef("same")), Set.copyOf(inherited.issueSources().get("same").members()));
        assertEquals(published.issueRef("same"), inherited.issueSources().get("same").headlineSources().get("label"));
        assertEquals(1, inherited.memberExclusions());
    }

    @Test
    void theOwnerAndTheLastMemberCannotBeExcludedAndASelectionCannotTakeFromAnExcludedOne() {
        Contribution published = source(0, "same", "A"); Contribution incoming = sameHeadline(published, source(1, "same", "A"));
        List<Contribution> all = List.of(published, incoming);
        var base = PublicationMerger.merge(List.of(published), PublicationMerger.emptyDecisions(), Set.of());
        assertEquals("identity_conflict", code(() -> PublicationMerger.merge(all, Obj.of(exclude(scoped(), "same", published, "excluded")),
                base.issueSources().keySet(), base.issueSources())));
        ObjectNode every = exclude(exclude(scoped(), "same", published, "excluded"), "same", incoming, "excluded");
        assertEquals("request_invalid", code(() -> PublicationMerger.merge(all, Obj.of(every), base.issueSources().keySet(), base.issueSources())));
        // Selections in the same file move every field first; then the old owner may leave.
        ObjectNode moved = selectAll(exclude(scoped(), "same", published, "excluded"), incoming);
        var merged = PublicationMerger.merge(all, Obj.of(moved), base.issueSources().keySet(), base.issueSources());
        assertEquals(List.of(incoming.issueRef("same")), merged.issueSources().get("same").members());
        assertEquals(Set.of(incoming.issueRef("same")), Set.copyOf(merged.issueSources().get("same").headlineSources().values()));
        assertEquals(incoming.projection().issues().getFirst().evidenceIds(), merged.issues().getFirst().evidenceIds());
        // A selection that takes from the excluded member is not grounded in the composition.
        ObjectNode fromExcluded = selectAll(exclude(scoped(), "same", incoming, "excluded"), incoming);
        assertEquals("mapping_unproven", code(() -> PublicationMerger.merge(all, Obj.of(fromExcluded), base.issueSources().keySet(), base.issueSources())));
        // A member outside the composition, or a member of another public issue, is no exclusion of this issue.
        Contribution other = source(2, "other", "C");
        assertEquals("mapping_unproven", code(() -> PublicationMerger.merge(all, Obj.of(exclude(scoped(), "same", other, "excluded")),
                base.issueSources().keySet(), base.issueSources())));
        assertEquals("mapping_unproven", code(() -> PublicationMerger.merge(List.of(published, incoming, other), Obj.of(exclude(scoped(), "same", other, "excluded")),
                base.issueSources().keySet(), base.issueSources())));
        assertEquals("mapping_unproven", code(() -> PublicationMerger.merge(all, Obj.of(retire(scoped(), "other", "retired")), base.issueSources().keySet(), base.issueSources())));
    }

    @Test
    void aRestoredMemberMergesAgainAndConflictsAreJudgedAmongValidMembersOnly() {
        Contribution published = source(0, "same", "A"); Contribution incoming = source(1, "same", "B");
        List<Contribution> all = List.of(published, incoming);
        var base = PublicationMerger.merge(List.of(published), PublicationMerger.emptyDecisions(), Set.of());
        assertEquals("correction_required", code(() -> PublicationMerger.merge(all, PublicationMerger.emptyDecisions(), base.issueSources().keySet(), base.issueSources())));
        Obj excluded = Obj.of(exclude(scoped(), "same", incoming, "excluded"));
        var merged = PublicationMerger.merge(all, excluded, base.issueSources().keySet(), base.issueSources());
        assertEquals("A", merged.issues().getFirst().label());
        // Restoring the member puts its value back into the comparison.
        Obj restored = PublicationMerger.combine(excluded, Obj.of(exclude(scoped(), "same", incoming, "restored")));
        assertEquals("correction_required", code(() -> PublicationMerger.merge(all, restored, merged.issueSources().keySet(), merged.issueSources())));
        var back = PublicationMerger.merge(List.of(published, sameHeadline(published, incoming)), PublicationMerger.combine(restored, labelOnly(published)),
                merged.issueSources().keySet(), merged.issueSources());
        assertEquals(2, back.issueSources().get("same").members().size());
        assertEquals(0, back.memberExclusions());
        assertEquals(2, back.evidence().size());
        // The automatic preparation compares valid members only: the excluded member's value is not a change.
        assertTrue(propose(all, PublicationMerger.emptyDecisions(), base, incoming).changes().stream().anyMatch(c -> "label".equals(c.field())));
        var silent = propose(all, excluded, base, incoming);
        assertEquals(List.of(), silent.changes()); assertEquals(List.of(), silent.sameHeadlines());
    }

    @Test
    void aRelationLosesOnlyTheExcludedProviderAndASelectionOfALostProviderIsNotCarried() {
        Contribution published = relation(source(0, "same", "A"), "shared");
        Contribution incoming = relation(sameHeadline(published, source(1, "same", "A")), "shared");
        List<Contribution> all = List.of(published, incoming);
        var base = PublicationMerger.merge(List.of(published), PublicationMerger.emptyDecisions(), Set.of());
        // Two providers with different records need a selection, unless the disagreeing provider's member is excluded.
        assertEquals("correction_required", code(() -> PublicationMerger.merge(all, PublicationMerger.emptyDecisions(), base.issueSources().keySet(), base.issueSources())));
        var merged = PublicationMerger.merge(all, Obj.of(exclude(scoped(), "same", incoming, "excluded")), base.issueSources().keySet(), base.issueSources());
        assertEquals(List.of(new GraphPublicationReader.RelationRef(published.sourceVersionId(), "shared")), merged.relationSources().get("shared").sources());
        // A selection that takes the record from the excluded provider stays unresolved until a person reselects.
        ObjectNode lost = exclude(relationSelection(scoped(), incoming, "shared"), "same", incoming, "excluded");
        assertEquals("identity_conflict", code(() -> PublicationMerger.merge(all, Obj.of(lost), base.issueSources().keySet(), base.issueSources())));
        // A relation only the excluded member provided leaves with it; its selection is kept dormant and counts as used...
        Contribution only = relation(sameHeadline(published, source(2, "same", "A")), "only");
        ObjectNode dormant = selectLabel(exclude(relationSelection(scoped(), only, "only"), "same", only, "excluded"), published);
        var without = PublicationMerger.merge(List.of(published, only), Obj.of(dormant), base.issueSources().keySet(), base.issueSources());
        assertEquals(Set.of("shared"), without.relationSources().keySet());
        assertEquals(without, PublicationMerger.merge(List.of(published, only), Obj.of(dormant), Set.of(), without.issueSources()));
        // ...while a forged record in it still fails, dormant or not.
        ObjectNode forged = exclude(relationSelection(scoped(), only, "only"), "same", only, "excluded");
        ((ObjectNode) forged.get("relationSelections").get(0).get("takeFrom")).put("relationId", "nowhere");
        assertEquals("identity_conflict", code(() -> PublicationMerger.merge(List.of(published, only), Obj.of(forged), base.issueSources().keySet(), base.issueSources())));
        // Once the provider is restored the dormant selection applies again.
        Obj restored = PublicationMerger.combine(Obj.of(dormant), Obj.of(exclude(scoped(), "same", only, "restored")));
        var back = PublicationMerger.merge(List.of(published, only), restored, without.issueSources().keySet(), without.issueSources());
        assertEquals(Set.of("shared", "only"), back.relationSources().keySet());
    }

    @Test
    void aRetiredIssueLeavesTheSnapshotKeepsItsReceiptEntryAndReturnsWithItsLastOwners() {
        Contribution published = source(0, "same", "A"); Contribution incoming = sameHeadline(published, source(1, "same", "A"));
        Contribution other = source(2, "other", "C");
        List<Contribution> all = List.of(published, incoming, other);
        // The published source owns every field, so a restoration that excludes it must reselect them all.
        var base = PublicationMerger.merge(all, Obj.of(selectAll((ObjectNode) PublicationMerger.emptyDecisions().node().deepCopy(), published)), Set.of());
        Obj retired = Obj.of(selectLabel(retire(scoped(), "same", "retired"), published));
        var merged = PublicationMerger.merge(all, retired, base.issueSources().keySet(), base.issueSources());
        assertEquals(List.of("other"), merged.issues().stream().map(Issue::issueId).toList());
        assertEquals(List.of("relation-2"), merged.relations().stream().map(PublicGraphSnapshot.Relation::relationId).toList());
        assertEquals(other.projection().articles(), merged.articles()); assertEquals(other.projection().evidence(), merged.evidence());
        assertEquals(base.companies(), merged.companies());
        assertEquals(base.issueSources().get("same"), merged.issueSources().get("same"));
        assertEquals(1, merged.issueRetirements()); assertEquals(0, merged.memberExclusions());
        assertEquals(merged, PublicationMerger.merge(all, retired, Set.of(), merged.issueSources()));
        // A later source carrying the issue is not attached, reports no change, and the id stays taken.
        Contribution later = sameHeadline(published, source(3, "same", "A"));
        List<Contribution> four = List.of(published, incoming, other, later);
        Obj carried = PublicationMerger.combine(retired, PublicationMerger.emptyDecisions());
        var next = PublicationMerger.merge(four, carried, merged.issueSources().keySet(), merged.issueSources());
        assertEquals(base.issueSources().get("same"), next.issueSources().get("same"));
        assertEquals(List.of("other"), next.issues().stream().map(Issue::issueId).toList());
        var proposal = PublicationMerger.propose(four, carried, merged.issueSources(), new PublicationMerger.Automatic(List.of(later.sourceVersionId())));
        assertEquals(List.of(), proposal.changes()); assertEquals(List.of(), proposal.sameHeadlines());
        assertEquals("identity_conflict", code(() -> PublicationMerger.merge(four, Obj.of(mapped(other, later)), merged.issueSources().keySet(), merged.issueSources())));
        // Restored: every valid member merges again under the owners approved last, not the default ones.
        Obj restored = PublicationMerger.combine(carried, Obj.of(retire(scoped(), "same", "restored")));
        var back = PublicationMerger.merge(four, restored, next.issueSources().keySet(), next.issueSources());
        assertEquals(List.of("other", "same"), back.issues().stream().map(Issue::issueId).toList());
        assertEquals(base.issueSources().get("same").headlineSources(), back.issueSources().get("same").headlineSources());
        assertEquals(3, back.issueSources().get("same").members().size());
        assertEquals(0, back.issueRetirements());
        // Restoring while the last owner is excluded in the same file needs a selection for every field it owned, not only label.
        Obj conflicting = PublicationMerger.combine(carried, Obj.of(selectLabel(exclude(retire(scoped(), "same", "restored"), "same", published, "excluded"), incoming)));
        assertEquals("identity_conflict", code(() -> PublicationMerger.merge(four, conflicting, next.issueSources().keySet(), next.issueSources())));
        // retired, restored, retired again: the last record is in force.
        Obj again = PublicationMerger.combine(restored, Obj.of(retire(scoped(), "same", "retired")));
        assertEquals(List.of("other"), PublicationMerger.merge(four, again, back.issueSources().keySet(), back.issueSources()).issues().stream().map(Issue::issueId).toList());
    }

    @Test
    void anIssueRetiredInItsFirstCompositionKeepsEveryMemberAndDormantDecisionsAreStillCheckedForShape() {
        Contribution published = source(0, "same", "A"); Contribution incoming = sameHeadline(published, source(1, "same", "A"));
        List<Contribution> all = List.of(published, incoming);
        var merged = PublicationMerger.merge(all, Obj.of(retire(scoped(), "same", "retired")), Set.of());
        assertEquals(List.of(), merged.issues());
        assertEquals(List.of(), merged.relations());
        var entry = merged.issueSources().get("same");
        assertEquals(2, entry.members().size());
        assertEquals(Set.of(entry.members().getFirst()), Set.copyOf(entry.headlineSources().values()));
        // A selection about the retired issue is kept and counts as used, and nothing is applied...
        ObjectNode dormant = retire(selectAll(scoped(), incoming), "same", "retired");
        var kept = PublicationMerger.merge(all, Obj.of(dormant), merged.issueSources().keySet(), merged.issueSources());
        assertEquals(entry, kept.issueSources().get("same"));
        // ...but a forged source in it still fails.
        ObjectNode forged = retire(selectAll(scoped(), incoming), "same", "retired");
        ((ObjectNode) forged.get("fieldSelections").get(0).get("takeFrom")).put("sourceVersionId", "gv-nowhere");
        assertEquals("mapping_unproven", code(() -> PublicationMerger.merge(all, Obj.of(forged), merged.issueSources().keySet(), merged.issueSources())));
        // On restoration the dormant selections apply: the owner moves.
        Obj restored = PublicationMerger.combine(Obj.of(dormant), Obj.of(retire(scoped(), "same", "restored")));
        var back = PublicationMerger.merge(all, restored, kept.issueSources().keySet(), kept.issueSources());
        assertEquals(Set.of(incoming.issueRef("same")), Set.copyOf(back.issueSources().get("same").headlineSources().values()));
    }

    @Test
    void sharedProofSurvivesARetirementAndUnionEntriesNoDecisionTouchedStay() {
        Contribution published = source(0, "same", "A");
        // One source carries issue "other" on the same article and evidence as its "same" record, and an article nothing cites.
        Contribution c = sameHeadline(published, source(1, "same", "A"));
        var p = c.projection(); Issue same = p.issues().getFirst();
        Issue other = new Issue("other", "C", null, "unknown", null, "occurred", "action", "target", "domestic", "policy",
                same.evidenceIds(), same.articleIds(), same.evidenceIds(), List.of(), null, "2026-10-01");
        var stray = new PublicGraphSnapshot.Article("doc-stray", "e".repeat(64), "Stray", "https://example.invalid/stray", "2026-10-01");
        var projection = new PublicGraphSnapshot(p.snapshotFormat(), p.versionId(), p.sourceBundleId(), p.companies(), List.of(same, other),
                List.of(p.relations().getFirst(), new PublicGraphSnapshot.Relation("relation-other", "INVOLVES", "other", "company", null, "occurred", same.evidenceIds(), List.of())),
                List.of(p.articles().getFirst(), stray), p.evidence());
        Contribution sharing = new Contribution(c.sourceVersionId(), c.sourceId(), c.sourceKind(), c.receipt(), c.projectionArtifact(), projection, c.bundle());
        List<Contribution> all = List.of(published, sharing);
        var base = PublicationMerger.merge(all, labelOnly(published), Set.of());
        assertTrue(base.articles().contains(stray));
        Obj retired = Obj.of(selectLabel(retire(scoped(), "same", "retired"), published));
        var merged = PublicationMerger.merge(all, retired, base.issueSources().keySet(), base.issueSources());
        assertEquals(List.of("other"), merged.issues().stream().map(Issue::issueId).toList());
        // The shared article and evidence stay for "other"; the owner's own proof leaves; the stray article was never a decision's target.
        assertEquals(Set.of(p.articles().getFirst(), stray), Set.copyOf(merged.articles()));
        assertEquals(p.evidence(), merged.evidence());
        assertEquals(merged, PublicationMerger.merge(all, retired, Set.of(), merged.issueSources()));
    }

    @Test
    void aFollowsRecordLeavesWithARetiredTargetAndItsBasisArticleGoesUnlessSomethingLiveCitesIt() {
        Contribution published = source(0, "same", "A"); Contribution other = source(2, "other", "C");
        var article = published.projection().articles().getFirst();
        // The second source carries "same" as an identical record and a FOLLOWS record other → same on a basis pinned to "same"'s article.
        var basis = new PublicGraphSnapshot.Basis("b-1", "FOLLOWS", "2026-10-01T00:00:00Z", null, null, List.of(),
                List.of(new PublicGraphSnapshot.ArticleRef(article.articleId(), article.version())));
        var follows = new PublicGraphSnapshot.Relation("follows-1", "FOLLOWS", "other", "same", null, "occurred", List.of(), List.of(basis));
        var p = other.projection();
        Contribution following = new Contribution(other.sourceVersionId(), other.sourceId(), other.sourceKind(), other.receipt(), other.projectionArtifact(),
                new PublicGraphSnapshot(p.snapshotFormat(), p.versionId(), p.sourceBundleId(), p.companies(),
                        List.of(p.issues().getFirst(), published.projection().issues().getFirst()), List.of(p.relations().getFirst(), follows), p.articles(), p.evidence()),
                other.bundle());
        List<Contribution> all = List.of(published, following);
        var base = PublicationMerger.merge(all, PublicationMerger.emptyDecisions(), Set.of());
        assertTrue(base.relations().stream().anyMatch(r -> r.relationId().equals("follows-1")));
        assertTrue(base.articles().contains(article));
        // Retiring the target drops the FOLLOWS record and the basis article nothing live cites any more.
        var merged = PublicationMerger.merge(all, Obj.of(retire(scoped(), "same", "retired")), base.issueSources().keySet(), base.issueSources());
        assertEquals(List.of("relation-2"), merged.relations().stream().map(PublicGraphSnapshot.Relation::relationId).toList());
        assertFalse(merged.articles().contains(article));
        assertEquals(merged, PublicationMerger.merge(all, Obj.of(retire(scoped(), "same", "retired")), Set.of(), merged.issueSources()));
        // Retiring the follower drops the record too, while the target's article stays with the target.
        var kept = PublicationMerger.merge(all, Obj.of(retire(scoped(), "other", "retired")), base.issueSources().keySet(), base.issueSources());
        assertEquals(List.of("relation-0"), kept.relations().stream().map(PublicGraphSnapshot.Relation::relationId).toList());
        assertTrue(kept.articles().contains(article));
    }

    private static ObjectNode scoped() {
        ObjectNode root = (ObjectNode) PublicationMerger.emptyDecisions().node().deepCopy();
        root.put("schemaVersion", PublicationMerger.DECISIONS_SCHEMA_3);
        root.putArray(PublicationMerger.LABEL_CORRECTIONS); root.putArray(PublicationMerger.MEMBER_EXCLUSIONS); root.putArray(PublicationMerger.ISSUE_RETIREMENTS);
        return root;
    }
    /** {@code root} with a record that {@code member}'s first issue is {@code status} as a member of public issue {@code issueId}. */
    private static ObjectNode exclude(ObjectNode root, String issueId, Contribution member, String status) {
        var item = ((tools.jackson.databind.node.ArrayNode) root.get(PublicationMerger.MEMBER_EXCLUSIONS)).addObject();
        item.put("issueId", issueId); item.set("member", GraphPublicationReader.json(member.issueRef(member.projection().issues().getFirst().issueId())));
        item.put("status", status); audit(item); return root;
    }
    private static ObjectNode retire(ObjectNode root, String issueId, String status) {
        var item = ((tools.jackson.databind.node.ArrayNode) root.get(PublicationMerger.ISSUE_RETIREMENTS)).addObject();
        item.put("issueId", issueId); item.put("status", status); audit(item); return root;
    }
    /** {@code root} with a {@code label} selection of {@code owner}'s first issue taken from {@code owner}: what two records that differ only in evidence need. */
    private static ObjectNode selectLabel(ObjectNode root, Contribution owner) {
        var issue = owner.projection().issues().getFirst();
        var choice = ((tools.jackson.databind.node.ArrayNode) root.get("fieldSelections")).addObject();
        choice.put("issueId", issue.issueId()); choice.put("field", "label");
        choice.put("expectedValueDigest", Canonical.digest(PublicationMerger.field(issue, "label")));
        choice.set("takeFrom", GraphPublicationReader.json(owner.issueRef(issue.issueId())));
        choice.putArray("evidenceRefs").add(evidenceRef(owner)); audit(choice); return root;
    }
    private static Obj labelOnly(Contribution owner) {
        return Obj.of(selectLabel((ObjectNode) PublicationMerger.emptyDecisions().node().deepCopy(), owner));
    }
    /** {@code root} with a selection of every headline field of {@code owner}'s first issue, taken from {@code owner}. */
    private static ObjectNode selectAll(ObjectNode root, Contribution owner) {
        var issue = owner.projection().issues().getFirst();
        for (String field : PublicationMerger.FIELDS) {
            var choice = ((tools.jackson.databind.node.ArrayNode) root.get("fieldSelections")).addObject();
            choice.put("issueId", issue.issueId()); choice.put("field", field);
            choice.put("expectedValueDigest", Canonical.digest(PublicationMerger.field(issue, field)));
            choice.set("takeFrom", GraphPublicationReader.json(owner.issueRef(issue.issueId())));
            choice.putArray("evidenceRefs").add(evidenceRef(owner)); audit(choice);
        }
        return root;
    }
    /** {@code root} with a selection of relation {@code relationId} that takes {@code owner}'s record and cites its evidence. */
    private static ObjectNode relationSelection(ObjectNode root, Contribution owner, String relationId) {
        var relation = owner.projection().relations().stream().filter(r -> r.relationId().equals(relationId)).findFirst().orElseThrow();
        var choice = ((tools.jackson.databind.node.ArrayNode) root.get("relationSelections")).addObject();
        choice.put("relationId", relationId); choice.put("expectedValueDigest", Canonical.digest(GraphPublicationReader.json(relation)));
        choice.set("takeFrom", GraphPublicationReader.json(new GraphPublicationReader.RelationRef(owner.sourceVersionId(), relationId)));
        choice.putArray("evidenceRefs").add(evidenceRef(owner)); audit(choice); return root;
    }

    private static String code(org.junit.jupiter.api.function.Executable call) {
        try { call.execute(); } catch (PublicationException failure) { return failure.code(); }
        catch (StrictJson.Malformed malformed) { return "request_invalid"; }
        catch (Throwable unexpected) { throw new AssertionError(unexpected); }
        return fail("expected a failure");
    }
    private static ObjectNode correction(ObjectNode decisions) {
        return (ObjectNode) decisions.get(PublicationMerger.LABEL_CORRECTIONS).get(0);
    }
    /** A second-schema decisions document that names {@code published}'s issue {@code label}, citing its own evidence. */
    private static ObjectNode corrected(Contribution published, String label) {
        ObjectNode root = (ObjectNode) PublicationMerger.emptyDecisions().node().deepCopy();
        root.put("schemaVersion", PublicationMerger.DECISIONS_SCHEMA_2);
        var issue = published.projection().issues().getFirst();
        var item = root.putArray(PublicationMerger.LABEL_CORRECTIONS).addObject();
        item.put("issueId", issue.issueId()); item.put("expectedLabelDigest", Canonical.digest(PublicationMerger.field(issue, "label")));
        item.put("label", label); item.putArray("evidenceRefs").add(evidenceRef(published)); audit(item);
        return root;
    }

    private record Prepared(PublicationMerger.Proposal proposal, Obj effective, PublicationMerger.Merged merged) {}

    private static PublicationMerger.Proposal propose(List<Contribution> all, Obj inherited, PublicationMerger.Merged base, Contribution... incoming) {
        return PublicationMerger.propose(all, inherited, base.issueSources(),
                new PublicationMerger.Automatic(java.util.Arrays.stream(incoming).map(Contribution::sourceVersionId).toList()));
    }

    /** Proposes, merges like the composer and re-merges like the reader (stored decisions and owners only). */
    private static Prepared prepare(List<Contribution> all, Obj inherited, PublicationMerger.Merged base, Contribution... incoming) {
        var proposal = propose(all, inherited, base, incoming);
        // The composer accepts a new decision only when it names the value published before (GraphPublicationComposer.compose);
        // for label that is the owner's source value, which a corrected name sits on top of.
        for (Obj choice : proposal.decisions().objects("fieldSelections")) {
            var previous = base.issues().stream().filter(i -> i.issueId().equals(choice.string("issueId"))).findFirst();
            previous.ifPresent(p -> {
                Issue published = "label".equals(choice.string("field")) ? all.stream()
                        .filter(c -> c.sourceVersionId().equals(base.issueSources().get(p.issueId()).headlineSources().get("label").sourceVersionId()))
                        .flatMap(c -> c.projection().issues().stream()).filter(i -> i.issueId().equals(base.issueSources().get(p.issueId()).headlineSources().get("label").issueId()))
                        .findFirst().orElseThrow() : p;
                assertEquals(Canonical.digest(PublicationMerger.field(published, choice.string("field"))), choice.string("expectedValueDigest"));
            });
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
        return peopleLabelOf(published);
    }
    /** A person's label selection of issue {@code same} that takes {@code owner}'s value and cites its evidence. */
    private static ObjectNode peopleLabelOf(Contribution owner) {
        ObjectNode people = (ObjectNode) PublicationMerger.emptyDecisions().node().deepCopy();
        var choice = ((tools.jackson.databind.node.ArrayNode) people.get("fieldSelections")).addObject();
        choice.put("issueId", "same"); choice.put("field", "label");
        choice.put("expectedValueDigest", Canonical.digest(PublicationMerger.field(owner.projection().issues().getFirst(), "label")));
        choice.set("takeFrom", GraphPublicationReader.json(owner.issueRef("same")));
        choice.putArray("evidenceRefs").add(evidenceRef(owner)); audit(choice);
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
    /** {@code original} with only its issue's headline label replaced. */
    private static Contribution relabel(Contribution original, String label) {
        Issue o = original.projection().issues().getFirst();
        Issue issue = new Issue(o.issueId(), label, o.eventTime(), o.timePrecision(), o.period(), o.assertionStatus(), o.action(), o.target(),
                o.geography(), o.geographyPolicyVersion(), o.geographyEvidenceIds(), o.articleIds(), o.evidenceIds(), o.mentions(),
                o.representativeMentionId(), o.latestPublishedAt());
        var x = original.projection();
        var projection = new PublicGraphSnapshot(x.snapshotFormat(), x.versionId(), x.sourceBundleId(), x.companies(), List.of(issue),
                x.relations(), x.articles(), x.evidence());
        return new Contribution(original.sourceVersionId(), original.sourceId(), original.sourceKind(), original.receipt(),
                original.projectionArtifact(), projection, original.bundle());
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
