package com.zoop.briefing.selection;

import java.time.Instant;
import java.time.LocalDate;
import java.time.ZoneId;
import java.util.List;
import java.util.Objects;

/** Internal owner-supplied facts, not an AI score or a new public API. No raw source text. */
public record SelectionInput(Context context, boolean sourceQuerySucceeded, List<Candidate> candidates) {
    public SelectionInput { Objects.requireNonNull(context); candidates = List.copyOf(candidates); }

    public enum Check { PASS, FAIL, UNKNOWN }
    public enum Novelty { NEW_MATERIAL_FACT, ADDITIONAL_CONFIRMATION, REPEAT, UNKNOWN }
    public enum Change { COMMON_POLICY, SYSTEMIC_DISRUPTION, LOCAL_MATERIAL, ROUTINE, UNKNOWN }
    public enum Channel { FINANCING, ENERGY, PAYMENTS, LOGISTICS, MARKET_ACCESS }
    public enum SourceKind { OFFICIAL_AUTHORITY, DIRECT_PRIMARY, VERIFIED_REPORT }

    public record Context(String roundId, String edition, Instant scheduledAt, Instant from,
            boolean firstRound, String graphVersion, long reviewRevision, long ruleRevision) {
        public Context {
            required(roundId); required(graphVersion); Objects.requireNonNull(scheduledAt);
            if (!List.of("morning", "evening").contains(edition)) throw new IllegalArgumentException("edition");
            var local = scheduledAt.atZone(ZoneId.of("Asia/Seoul"));
            var expected = com.zoop.briefing.market.BriefingRoundClock.time(edition);
            if (!local.toLocalTime().equals(expected)) throw new IllegalArgumentException("09:20/17:30 KST required");
            if ((from == null) != firstRound || (from != null && !from.isBefore(scheduledAt)))
                throw new IllegalArgumentException("Only first round has an open start");
            if (reviewRevision < 0 || ruleRevision < 1) throw new IllegalArgumentException("revision");
        }
    }

    /** Exactly one of exact or (date, zone); never manufacture midnight for ranking. */
    public record PublicationTime(Instant exact, LocalDate date, ZoneId zone) {
        public PublicationTime {
            if (exact != null ? date != null || zone != null : date == null || zone == null)
                throw new IllegalArgumentException("publication precision");
        }
        public static PublicationTime exact(Instant at) { return new PublicationTime(Objects.requireNonNull(at), null, null); }
        public static PublicationTime date(LocalDate date, ZoneId zone) { return new PublicationTime(null, date, zone); }
    }

    public record Grant(String id, String revision, Check decision, List<String> requiredOperations,
            List<String> requiredPurposes, List<String> requiredRecipients) {
        public Grant {
            Objects.requireNonNull(decision);
            requiredOperations = List.copyOf(requiredOperations); requiredPurposes = List.copyOf(requiredPurposes);
            requiredRecipients = List.copyOf(requiredRecipients);
            requiredOperations.forEach(SelectionInput::required); requiredPurposes.forEach(SelectionInput::required);
            requiredRecipients.forEach(SelectionInput::required);
            if (decision == Check.PASS) {
                required(id); required(revision);
                if (requiredOperations.isEmpty() || requiredPurposes.isEmpty() || requiredRecipients.isEmpty())
                    throw new IllegalArgumentException("Actual checked grant scope required");
            }
        }
    }

    /** checkedScope is the full operations/purposes/recipients required by this response, not summary-only. */
    public record Evidence(String id, String articleId, String articleVersion, String textArtifactId,
            String analysisId, PublicationTime published, Instant collectedAt, Grant checkedScope,
            Check verification, boolean quoteMatches, boolean versionMatches, SourceKind sourceKind,
            String independentLineage) {
        public Evidence {
            required(id); required(articleId); required(articleVersion);
            // Unregistered imports carry null, never invented registry IDs. The selector holds them.
            optionalReference(textArtifactId); optionalReference(analysisId);
            Objects.requireNonNull(published); Objects.requireNonNull(collectedAt);
            Objects.requireNonNull(checkedScope); Objects.requireNonNull(verification); Objects.requireNonNull(sourceKind);
        }
        public boolean primary() { return sourceKind != SourceKind.VERIFIED_REPORT; }
    }

    /** A verified causal link, with evidence proving actual material effect in the named sector. */
    public record SectorEffect(String sectorId, List<String> evidenceIds) {
        public SectorEffect { required(sectorId); evidenceIds = List.copyOf(evidenceIds); }
    }

    public record Impact(Change change, boolean material, boolean marketWideRule,
            Channel systemicChannel, String mechanism, String scopeBasisRef, List<String> evidenceIds, List<SectorEffect> sectorEffects) {
        public Impact {
            Objects.requireNonNull(change); evidenceIds = List.copyOf(evidenceIds); sectorEffects = List.copyOf(sectorEffects);
        }
    }

    /** One authoritative canonical event group. Alias/title deduplication belongs to the source owner. */
    public record Candidate(String eventId, String eventVersion, String canonicalizationRef,
            String graphVersion, long reviewRevision, long ruleRevision, Check currentVerification,
            boolean conflictingEvidence, Novelty novelty, String factDeltaRef, List<String> factEvidenceIds,
            Impact impact, List<Evidence> evidence) {
        public Candidate {
            required(eventId); required(eventVersion); optionalReference(canonicalizationRef); required(graphVersion);
            Objects.requireNonNull(currentVerification); Objects.requireNonNull(novelty); Objects.requireNonNull(impact);
            factEvidenceIds = List.copyOf(factEvidenceIds); evidence = List.copyOf(evidence);
        }
    }

    static void required(String s) { if (s == null || s.isBlank()) throw new IllegalArgumentException("Nonblank owner reference required"); }
    static void optionalReference(String s) { if (s != null) required(s); }
}
