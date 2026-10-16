package com.zoop.briefing.selection;

import java.time.*;
import java.util.*;
import org.junit.jupiter.api.Test;
import static org.junit.jupiter.api.Assertions.*;
import static com.zoop.briefing.selection.SelectionInput.*;

public class BriefingCandidateSelectorTest {
    public static final Instant CUTOFF = Instant.parse("2026-10-15T00:20:00Z");
    public static Context context() {
        return new Context("round", "morning", CUTOFF, Instant.parse("2026-10-14T08:30:00Z"), false, "g1", 2, 3);
    }
    public static Evidence evidence(String id, Instant at, boolean primary, String lineage) {
        return new Evidence(id, "article-" + id, "v1", "text-" + id, "analysis-" + id, PublicationTime.exact(at),
            at, new Grant("grant", "1", Check.PASS, List.of("quote", "summarize"), List.of("briefing"), List.of("public")),
            Check.PASS, true, true, primary ? SourceKind.OFFICIAL_AUTHORITY : SourceKind.VERIFIED_REPORT, lineage);
    }
    public static Candidate candidate(String id, Impact impact, Novelty novelty, Evidence... evidence) {
        return new Candidate(id, "event-v1", "canonical-" + id, "g1", 2, 3, Check.PASS, false,
            novelty, "delta-" + id, List.of(evidence[0].id()), impact, List.of(evidence));
    }
    public static Impact local(String evidenceId) {
        return new Impact(Change.LOCAL_MATERIAL, true, false, null, "verified earnings change", "owner-impact-scope-v1", List.of(evidenceId), List.of());
    }
    public static SelectionInput input(Candidate... c) { return new SelectionInput(context(), true, List.of(c)); }
    private final BriefingCandidateSelector selector = new BriefingCandidateSelector();
    private Evidence source(String id) { return evidence(id, CUTOFF.minusSeconds(600), true, "origin"); }
    private BriefingCandidateSelector.Decision decision(Candidate c) { return selector.select(input(c)).audit().getFirst(); }
    private Candidate withEvidence(Candidate c, Evidence e) {
        return new Candidate(c.eventId(), c.eventVersion(), c.canonicalizationRef(), c.graphVersion(), c.reviewRevision(),
            c.ruleRevision(), c.currentVerification(), c.conflictingEvidence(), c.novelty(), c.factDeltaRef(),
            c.factEvidenceIds(), c.impact(), List.of(e));
    }
    private Evidence withTime(Evidence e, PublicationTime time, Instant collected) {
        return new Evidence(e.id(), e.articleId(), e.articleVersion(), e.textArtifactId(), e.analysisId(), time, collected,
            e.checkedScope(), e.verification(), e.quoteMatches(), e.versionMatches(), e.sourceKind(), e.independentLineage());
    }

    @Test void policyScopeAndMaterialFactAreRequiredForGradeThree() {
        var impact = new Impact(Change.COMMON_POLICY, true, true, null, "common funding rule changed", "owner-impact-scope-v1", List.of("e"), List.of());
        assertEquals(3, decision(candidate("policy", impact, Novelty.NEW_MATERIAL_FACT, source("e"))).importance());
        var companyRule = new Impact(Change.COMMON_POLICY, true, false, null, "one-company rule", "owner-impact-scope-v1", List.of("e"), List.of());
        assertEquals(2, decision(candidate("company", companyRule, Novelty.NEW_MATERIAL_FACT, source("e"))).importance());
        var unproven = new Impact(Change.COMMON_POLICY, false, true, null, "rumor", "owner-impact-scope-v1", List.of("e"), List.of());
        assertEquals("impact_basis_incomplete", decision(candidate("rumor", unproven, Novelty.NEW_MATERIAL_FACT, source("e"))).reason());
    }
    @Test void systemicDisruptionRequiresVerifiedDistinctSectorsAndChannel() {
        var impact = new Impact(Change.SYSTEMIC_DISRUPTION, true, false, Channel.ENERGY, "actual supply interruption",
            "owner-impact-scope-v1", List.of("e"), List.of(new SectorEffect("transport", List.of("e")), new SectorEffect("manufacturing", List.of("e"))));
        assertEquals(3, decision(candidate("systemic", impact, Novelty.NEW_MATERIAL_FACT, source("e"))).importance());
        var duplicateSector = new Impact(Change.SYSTEMIC_DISRUPTION, true, false, Channel.ENERGY, "same sector twice",
            "owner-impact-scope-v1", List.of("e"), List.of(new SectorEffect("transport", List.of("e")), new SectorEffect("transport", List.of("e"))));
        assertEquals(2, decision(candidate("same", duplicateSector, Novelty.NEW_MATERIAL_FACT, source("e"))).importance());
        var brokenLink = new Impact(Change.SYSTEMIC_DISRUPTION, true, false, Channel.ENERGY, "unproven impact",
            "owner-impact-scope-v1", List.of("e"), List.of(new SectorEffect("a", List.of("missing")), new SectorEffect("b", List.of("e"))));
        assertEquals("impact_basis_incomplete", decision(candidate("broken", brokenLink, Novelty.NEW_MATERIAL_FACT, source("e"))).reason());
    }
    @Test void systemicDisruptionWithoutAffectedSectorEvidenceIsHeldInsteadOfDowngraded() {
        var impact = new Impact(Change.SYSTEMIC_DISRUPTION, true, false, Channel.ENERGY,
            "interruption without proven sector impact", "scope", List.of("e"), List.of());
        var result = selector.select(input(candidate("missing-sectors", impact, Novelty.NEW_MATERIAL_FACT, source("e"))));
        assertTrue(result.selected().isEmpty());
        var audit = result.audit().getFirst();
        assertEquals(BriefingCandidateSelector.Disposition.HELD, audit.disposition());
        assertEquals("impact_basis_incomplete", audit.reason());
    }
    @Test void largeCompanyOrAmountAloneNeverUpgradesLocalChange() {
        var impact = new Impact(Change.LOCAL_MATERIAL, true, true, Channel.FINANCING, "very large company, huge amount",
            "owner-impact-scope-v1", List.of("e"), List.of(new SectorEffect("a", List.of("e")), new SectorEffect("b", List.of("e"))));
        assertEquals(2, decision(candidate("large", impact, Novelty.NEW_MATERIAL_FACT, source("e"))).importance());
    }
    @Test void marketWideClaimWithoutScopeProofOrSystemicChannelIsHeld() {
        var policy = new Impact(Change.COMMON_POLICY, true, true, null, "policy", null, List.of("e"), List.of());
        assertEquals("impact_basis_incomplete", decision(candidate("policy", policy, Novelty.NEW_MATERIAL_FACT, source("e"))).reason());
        var disruption = new Impact(Change.SYSTEMIC_DISRUPTION, true, false, null, "disruption", "scope",
            List.of("e"), List.of(new SectorEffect("a", List.of("e")), new SectorEffect("b", List.of("e"))));
        assertEquals("impact_basis_incomplete", decision(candidate("disruption", disruption, Novelty.NEW_MATERIAL_FACT, source("e"))).reason());
    }
    @Test void gradeThreeRequiresOfficialOrTwoIndependentPrimaryFactSources() {
        var impact = new Impact(Change.COMMON_POLICY, true, true, null, "funding rule", "scope", List.of("a"), List.of());
        var report = evidence("a", CUTOFF.minusSeconds(1), false, "report-origin");
        assertEquals("market_impact_confirmation_incomplete", decision(candidate("policy", impact, Novelty.NEW_MATERIAL_FACT, report)).reason());
        var a = new Evidence("a", "article-a", "v", "text-a", "analysis-a", report.published(), report.collectedAt(),
            report.checkedScope(), Check.PASS, true, true, SourceKind.DIRECT_PRIMARY, "origin-a");
        var b = new Evidence("b", "article-b", "v", "text-b", "analysis-b", report.published(), report.collectedAt(),
            report.checkedScope(), Check.PASS, true, true, SourceKind.DIRECT_PRIMARY, "origin-b");
        var group = new Candidate("policy", "v", "canon", "g1", 2, 3, Check.PASS, false, Novelty.NEW_MATERIAL_FACT,
            "delta", List.of("a", "b"), impact, List.of(a, b));
        assertEquals(1, selector.select(input(group)).selected().size());
        assertEquals(3, decision(group).importance());
    }
    @Test void missingImpactProofIsHeldRatherThanZeroOrLowScore() {
        var impact = new Impact(Change.LOCAL_MATERIAL, true, false, null, "material", "owner-impact-scope-v1", List.of("missing"), List.of());
        assertEquals(BriefingCandidateSelector.Disposition.HELD,
            decision(candidate("missing", impact, Novelty.NEW_MATERIAL_FACT, source("e"))).disposition());
    }
    @Test void zeroOneAndTopThreeAreAllowedAndPermutationInvariant() {
        assertTrue(selector.select(input()).selected().isEmpty());
        var list = new ArrayList<Candidate>();
        for (String id : List.of("a", "b", "c", "d")) list.add(candidate(id, local("e"), Novelty.NEW_MATERIAL_FACT, source("e")));
        var baseline = selector.select(new SelectionInput(context(), true, list));
        assertEquals(List.of("a", "b", "c"), baseline.selected().stream().map(BriefingCandidateSelector.Decision::eventId).toList());
        for (int n = 0; n < 50; n++) {
            Collections.shuffle(list, new Random(n));
            assertEquals(baseline, selector.select(new SelectionInput(context(), true, list)));
        }
        assertEquals(1, selector.select(input(list.getFirst())).selected().size());
    }
    @Test void finalTieUsesUnicodeCodePointsRatherThanUtf16Surrogates() {
        assertTrue(BriefingCandidateSelector.compareCodePoints("\uE000", "\uD800\uDC00") < 0);
    }
    @Test void noveltyClassThenDirectProofThenActualFactTimeDetermineTies() {
        var oldPrimary = candidate("old", local("e1"), Novelty.NEW_MATERIAL_FACT,
            evidence("e1", CUTOFF.minusSeconds(300), true, null));
        var newSingle = candidate("new", local("e2"), Novelty.NEW_MATERIAL_FACT,
            evidence("e2", CUTOFF.minusSeconds(1), false, null));
        var confirmation = candidate("confirmation", local("e3"), Novelty.ADDITIONAL_CONFIRMATION,
            evidence("e3", CUTOFF.minusSeconds(1), true, null));
        assertEquals(List.of("old", "new", "confirmation"), selector.select(input(confirmation, newSingle, oldPrimary))
            .selected().stream().map(BriefingCandidateSelector.Decision::eventId).toList());
    }
    @Test void duplicateRepostsCannotCreateIndependentConfirmationOrRefreshFactTime() {
        var first = evidence("first", CUTOFF.minusSeconds(600), false, "wire");
        var repost = evidence("copy", CUTOFF.minusSeconds(1), false, "wire");
        var group = candidate("group", local("first"), Novelty.NEW_MATERIAL_FACT, first, repost);
        var other = candidate("other", local("other-proof"), Novelty.NEW_MATERIAL_FACT,
            evidence("other-proof", CUTOFF.minusSeconds(300), false, null));
        assertEquals("other", selector.select(input(group, other)).selected().getFirst().eventId());
    }
    @Test void independentlyVerifiedFactSourcesAreStrongButUnknownLineageIsNot() {
        var a = evidence("a", CUTOFF.minusSeconds(600), false, "owner-a");
        var b = evidence("b", CUTOFF.minusSeconds(600), false, "owner-b");
        var group = new Candidate("group", "v", "canon", "g1", 2, 3, Check.PASS, false, Novelty.NEW_MATERIAL_FACT,
            "delta", List.of("a", "b"), local("a"), List.of(a, b));
        var single = candidate("single", local("s"), Novelty.NEW_MATERIAL_FACT,
            evidence("s", CUTOFF.minusSeconds(1), false, null));
        assertEquals("group", selector.select(input(single, group)).selected().getFirst().eventId());
    }
    @Test void invalidRepostIsAuditedAndCannotBoostUsableFact() {
        var original = source("e");
        var invalid = new Evidence("bad", "bad-article", "v", "text", "analysis", PublicationTime.exact(CUTOFF), CUTOFF,
            original.checkedScope(), Check.FAIL, true, true, SourceKind.OFFICIAL_AUTHORITY, "independent");
        var result = decision(candidate("group", local("e"), Novelty.NEW_MATERIAL_FACT, original, invalid));
        assertEquals(List.of("e"), result.usableEvidenceIds());
        assertEquals("evidence_invalid", result.evidenceDecisions().getFirst().reason());
    }
    @Test void cutoffInclusiveLowerExclusiveAndLateCaptureExcluded() {
        var e = source("e"); var c = candidate("x", local("e"), Novelty.NEW_MATERIAL_FACT, e);
        assertEquals(1, selector.select(input(withEvidence(c, withTime(e, PublicationTime.exact(CUTOFF), CUTOFF)))).selected().size());
        assertEquals("no_usable_evidence", decision(withEvidence(c,
            withTime(e, PublicationTime.exact(context().from()), context().from()))).reason());
        assertEquals("no_usable_evidence", decision(withEvidence(c,
            withTime(e, PublicationTime.exact(CUTOFF.minusSeconds(1)), CUTOFF.plusNanos(1)))).reason());
    }
    @Test void dateOnlyMustFitEntirePossibleIntervalAndDoesNotInventRankingTime() {
        var e = source("e"); var c = candidate("date", local("e"), Novelty.NEW_MATERIAL_FACT, e);
        var today = withTime(e, PublicationTime.date(LocalDate.of(2026, 10, 15), ZoneId.of("Asia/Seoul")), CUTOFF);
        assertEquals(1, selector.select(input(withEvidence(c, today))).selected().size());
        var yesterday = withTime(e, PublicationTime.date(LocalDate.of(2026, 10, 14), ZoneId.of("Asia/Seoul")), CUTOFF);
        assertEquals("no_proven_usable_evidence", decision(withEvidence(c, yesterday)).reason());
        assertEquals("time_ambiguous", decision(withEvidence(c, yesterday)).evidenceDecisions().getFirst().reason());
        var capturedBeforeStart = withTime(e, yesterday.published(), context().from());
        assertEquals("outside_window", decision(withEvidence(c, capturedBeforeStart)).evidenceDecisions().getFirst().reason());
    }
    @Test void equivalentOriginalOffsetMapsToSameInstant() {
        assertEquals(CUTOFF, OffsetDateTime.parse("2026-10-15T09:20:00+09:00").toInstant());
        var e = evidence("e", OffsetDateTime.parse("2026-10-14T20:20:00-04:00").toInstant(), true, null);
        assertEquals(1, selector.select(input(candidate("offset", local("e"), Novelty.NEW_MATERIAL_FACT, e))).selected().size());
    }
    @Test void unknownRightsAreHeldAndMarkDegradedNotSuccessfulNoIssues() {
        var e = source("e");
        var unknown = new Evidence(e.id(), e.articleId(), e.articleVersion(), e.textArtifactId(), e.analysisId(), e.published(),
            e.collectedAt(), new Grant(null, null, Check.UNKNOWN, List.of(), List.of(), List.of()),
            e.verification(), true, true, e.sourceKind(), null);
        var result = selector.select(input(candidate("x", local("e"), Novelty.NEW_MATERIAL_FACT, unknown)));
        assertTrue(result.degraded()); assertTrue(result.selected().isEmpty());
        assertEquals(BriefingCandidateSelector.Disposition.HELD, result.audit().getFirst().disposition());
    }
    @Test void pendingAllowAndStaleVersionsCannotBeSelected() {
        var c = candidate("x", local("e"), Novelty.NEW_MATERIAL_FACT, source("e"));
        var pending = new Candidate(c.eventId(), c.eventVersion(), c.canonicalizationRef(), "g1", 2, 3, Check.UNKNOWN, false,
            c.novelty(), c.factDeltaRef(), c.factEvidenceIds(), c.impact(), c.evidence());
        assertEquals("verification_pending", decision(pending).reason());
        var stale = new Candidate(c.eventId(), c.eventVersion(), c.canonicalizationRef(), "g0", 2, 3, Check.PASS, false,
            c.novelty(), c.factDeltaRef(), c.factEvidenceIds(), c.impact(), c.evidence());
        assertEquals("basis_changed", decision(stale).reason());
    }
    @Test void repeatsAndUnknownNoveltyAreNotCoreButVerifiedNewFactCanReappear() {
        assertEquals("repeat", decision(candidate("same-event", local("e"), Novelty.REPEAT, source("e"))).reason());
        assertEquals("novelty_unknown", decision(candidate("same-event", local("e"), Novelty.UNKNOWN, source("e"))).reason());
        assertEquals(1, selector.select(input(candidate("same-event", local("e"), Novelty.NEW_MATERIAL_FACT, source("e")))).selected().size());
    }
    @Test void conflictingReportsRemainHeldAndRoutineDoesNotFillQuota() {
        var c = candidate("x", local("e"), Novelty.NEW_MATERIAL_FACT, source("e"));
        var conflict = new Candidate(c.eventId(), c.eventVersion(), c.canonicalizationRef(), "g1", 2, 3, Check.PASS, true,
            c.novelty(), c.factDeltaRef(), c.factEvidenceIds(), c.impact(), c.evidence());
        assertEquals("conflicting_evidence", decision(conflict).reason());
        var routine = new Impact(Change.ROUTINE, false, false, null, "routine promotion", "owner-impact-scope-v1", List.of("e"), List.of());
        assertEquals("routine_not_core", decision(candidate("routine", routine, Novelty.NEW_MATERIAL_FACT, source("e"))).reason());
    }
    @Test void missingCanonicalizationAndDuplicateCanonicalGroupFailInsteadOfTitleMerge() {
        var c = candidate("x", local("e"), Novelty.NEW_MATERIAL_FACT, source("e"));
        assertThrows(IllegalArgumentException.class, () -> selector.select(input(c, c)));
        assertThrows(IllegalArgumentException.class, () -> new Candidate("x", "v", "", "g1", 2, 3, Check.PASS,
            false, Novelty.NEW_MATERIAL_FACT, "delta", List.of("e"), local("e"), List.of(source("e"))));
    }
    @Test void failedSourceQueryIsNotEmptySuccessfulSelection() {
        assertThrows(IllegalStateException.class, () -> selector.select(new SelectionInput(context(), false, List.of())));
    }
    @Test void firstRoundOnlyOpenStartAndGenerationTimesValidated() {
        assertDoesNotThrow(() -> new Context("first", "morning", CUTOFF, null, true, "g1", 0, 1));
        assertThrows(IllegalArgumentException.class, () -> new Context("middle", "morning", CUTOFF, null, false, "g1", 0, 1));
        assertThrows(IllegalArgumentException.class, () -> new Context("wrong", "morning", CUTOFF.plusSeconds(1), null, true, "g1", 0, 1));
    }
}
