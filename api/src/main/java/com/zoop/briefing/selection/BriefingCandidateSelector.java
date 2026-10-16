package com.zoop.briefing.selection;

import java.time.Instant;
import java.util.*;
import static com.zoop.briefing.selection.SelectionInput.*;

/** Deterministic selection only. Does not query an owner, run a model, acquire a lease or publish. */
public final class BriefingCandidateSelector {
    public static final String POLICY_VERSION = "briefing-selection-v1";
    public enum Disposition { SELECTED, BELOW_CUTOFF, EXCLUDED, HELD }
    public record EvidenceDecision(String evidenceId, String reason) {}
    public record Decision(String eventId, Disposition disposition, String reason, int importance, Integer rank,
            List<String> usableEvidenceIds, List<EvidenceDecision> evidenceDecisions) {
        public Decision { usableEvidenceIds = List.copyOf(usableEvidenceIds); evidenceDecisions = List.copyOf(evidenceDecisions); }
    }
    public record Result(String policyVersion, List<Decision> selected, List<Decision> audit, boolean degraded) {
        public Result { selected = List.copyOf(selected); audit = List.copyOf(audit); }
    }
    private record Scored(Candidate candidate, Decision decision, int novelty, int support, Instant factTime) {}

    public Result select(SelectionInput input) {
        if (!input.sourceQuerySucceeded()) throw new IllegalStateException("SOURCE_UNAVAILABLE: candidate query failed");
        var candidates = new ArrayList<>(input.candidates());
        candidates.sort((a, b) -> compareCodePoints(a.eventId(), b.eventId()));
        var seen = new HashSet<String>();
        var scored = new ArrayList<Scored>();
        var audit = new TreeMap<String, Decision>(BriefingCandidateSelector::compareCodePoints);
        boolean degraded = false;
        for (var c : candidates) {
            if (!seen.add(c.eventId())) throw new IllegalArgumentException("Duplicate canonical event group: " + c.eventId());
            var evidenceIds = new HashSet<String>();
            var usable = new TreeMap<String, Evidence>();
            var checks = new ArrayList<EvidenceDecision>();
            for (var e : c.evidence()) {
                if (!evidenceIds.add(e.id())) throw new IllegalArgumentException("Duplicate evidence id");
                String reason = evidenceReason(e, input.context());
                checks.add(new EvidenceDecision(e.id(), reason));
                if (reason.equals("usable")) usable.put(e.id(), e);
                if (Set.of("rights_unknown", "source_registration_missing").contains(reason)) degraded = true;
            }
            checks.sort(Comparator.comparing(EvidenceDecision::evidenceId));
            String held = null, excluded = null;
            var ctx = input.context();
            if (!c.graphVersion().equals(ctx.graphVersion()) || c.reviewRevision() != ctx.reviewRevision()
                    || c.ruleRevision() != ctx.ruleRevision()) held = "basis_changed";
            else if (c.conflictingEvidence()) held = "conflicting_evidence";
            else if (c.currentVerification() == Check.UNKNOWN) held = "verification_pending";
            else if (c.currentVerification() == Check.FAIL) excluded = "verification_failed";
            else if (blank(c.canonicalizationRef())) held = "canonicalization_pending";
            else if (usable.isEmpty()) {
                if (checks.stream().anyMatch(e -> Set.of("rights_unknown", "verification_pending", "time_ambiguous", "source_registration_missing").contains(e.reason())))
                    held = "no_proven_usable_evidence";
                else excluded = "no_usable_evidence";
            } else if (c.novelty() == Novelty.REPEAT) excluded = "repeat";
            else if (c.novelty() == Novelty.UNKNOWN || blank(c.factDeltaRef())) held = "novelty_unknown";
            else if (!allUsable(c.factEvidenceIds(), usable.keySet())) held = "fact_basis_incomplete";

            int grade = 0;
            String impactReason = null;
            if (held == null && excluded == null) {
                grade = importance(c.impact(), usable.keySet());
                impactReason = switch (grade) {
                    case 3 -> c.impact().change() == Change.COMMON_POLICY ? "market_common_rule_change" : "systemic_multi_sector_effect";
                    case 2 -> "verified_material_change";
                    case 1 -> "routine_not_core";
                    default -> "impact_basis_incomplete";
                };
                if (grade == 0) held = impactReason;
                if (grade == 1) excluded = impactReason;
                if (grade == 3) {
                    var facts = c.factEvidenceIds().stream().map(usable::get).toList();
                    boolean officialOrIndependentPrimary = facts.stream().anyMatch(e -> e.sourceKind() == SourceKind.OFFICIAL_AUTHORITY)
                        || facts.stream().filter(Evidence::primary).map(Evidence::independentLineage)
                            .filter(s -> !blank(s)).distinct().count() >= 2;
                    if (!officialOrIndependentPrimary) held = "market_impact_confirmation_incomplete";
                }
            }
            var decision = new Decision(c.eventId(), held != null ? Disposition.HELD : Disposition.EXCLUDED,
                held != null ? held : excluded, grade, null, new ArrayList<>(usable.keySet()), checks);
            if (held != null) degraded = true; // A held group must not masquerade as a normal empty round.
            if (held != null || excluded != null) audit.put(c.eventId(), decision);
            else {
                var facts = c.factEvidenceIds().stream().map(usable::get).toList();
                boolean strong = facts.stream().anyMatch(Evidence::primary) || facts.stream()
                    .map(Evidence::independentLineage).filter(s -> !blank(s)).distinct().count() >= 2;
                // Only fact-bearing evidence sets freshness; a later syndicated repost cannot refresh it.
                Instant factTime = facts.stream().anyMatch(e -> e.published().exact() == null) ? null : facts.stream()
                    .map(e -> e.published().exact()).min(Comparator.naturalOrder()).orElse(null);
                var eligible = new Decision(c.eventId(), Disposition.BELOW_CUTOFF, impactReason, grade, null,
                    new ArrayList<>(usable.keySet()), checks);
                scored.add(new Scored(c, eligible, c.novelty() == Novelty.NEW_MATERIAL_FACT ? 2 : 1, strong ? 2 : 1, factTime));
            }
        }
        scored.sort(Comparator.<Scored>comparingInt(s -> s.decision().importance()).reversed()
            .thenComparing(Comparator.comparingInt(Scored::novelty).reversed())
            .thenComparing(Comparator.comparingInt(Scored::support).reversed())
            .thenComparing(Scored::factTime, Comparator.nullsLast(Comparator.reverseOrder()))
            .thenComparing(s -> s.candidate().eventId(), BriefingCandidateSelector::compareCodePoints));
        var selected = new ArrayList<Decision>();
        for (int i = 0; i < scored.size(); i++) {
            var s = scored.get(i).decision();
            var d = new Decision(s.eventId(), i < 3 ? Disposition.SELECTED : Disposition.BELOW_CUTOFF,
                i < 3 ? s.reason() : "rank_after_top_three", s.importance(), i < 3 ? i + 1 : null,
                s.usableEvidenceIds(), s.evidenceDecisions());
            audit.put(d.eventId(), d);
            if (i < 3) selected.add(d);
        }
        return new Result(POLICY_VERSION, selected, new ArrayList<>(audit.values()), degraded);
    }

    private static int importance(Impact impact, Set<String> usable) {
        if (impact.change() == Change.UNKNOWN || blank(impact.mechanism()) || !allUsable(impact.evidenceIds(), usable)) return 0;
        if (impact.change() == Change.ROUTINE) return 1;
        if (!impact.material()) return 0;
        if (impact.change() == Change.COMMON_POLICY)
            return impact.marketWideRule() ? (blank(impact.scopeBasisRef()) ? 0 : 3) : 2;
        if (impact.change() == Change.SYSTEMIC_DISRUPTION) {
            if (impact.systemicChannel() == null || blank(impact.scopeBasisRef()) || impact.sectorEffects().isEmpty()) return 0;
            var sectors = new HashSet<String>();
            for (var effect : impact.sectorEffects()) {
                if (!allUsable(effect.evidenceIds(), usable)) return 0;
                sectors.add(effect.sectorId());
            }
            return sectors.size() >= 2 ? 3 : 2;
        }
        return 2;
    }

    private static String evidenceReason(Evidence e, Context c) {
        if (blank(e.textArtifactId()) || blank(e.analysisId())) return "source_registration_missing";
        if (!e.versionMatches()) return "version_mismatch";
        if (e.checkedScope().decision() == Check.FAIL) return "rights_denied";
        if (e.checkedScope().decision() == Check.UNKNOWN) return "rights_unknown";
        if (e.verification() == Check.UNKNOWN) return "verification_pending";
        if (e.verification() == Check.FAIL || !e.quoteMatches()) return "evidence_invalid";
        if (e.collectedAt().isAfter(c.scheduledAt())) return "collected_after_cutoff";
        var time = e.published();
        if (time.exact() != null) {
            if (time.exact().isAfter(e.collectedAt())) return "publication_after_capture";
            return time.exact().isAfter(c.scheduledAt()) || (c.from() != null && !time.exact().isAfter(c.from()))
                ? "outside_window" : "usable";
        }
        Instant earliest = time.date().atStartOfDay(time.zone()).toInstant();
        Instant latestExclusive = time.date().plusDays(1).atStartOfDay(time.zone()).toInstant();
        if (e.collectedAt().isBefore(earliest)) return "publication_after_capture";
        if (c.from() != null && !e.collectedAt().isAfter(c.from())) return "outside_window";
        if (earliest.isAfter(c.scheduledAt()) || (c.from() != null && !latestExclusive.isAfter(c.from()))) return "outside_window";
        return c.from() != null && !earliest.isAfter(c.from()) ? "time_ambiguous" : "usable";
    }

    private static boolean allUsable(List<String> ids, Set<String> usable) {
        return !ids.isEmpty() && usable.containsAll(ids);
    }
    private static boolean blank(String s) { return s == null || s.isBlank(); }
    public static int compareCodePoints(String a, String b) {
        var x = a.codePoints().iterator(); var y = b.codePoints().iterator();
        while (x.hasNext() && y.hasNext()) { int d = Integer.compare(x.nextInt(), y.nextInt()); if (d != 0) return d; }
        return Boolean.compare(x.hasNext(), y.hasNext());
    }
}
