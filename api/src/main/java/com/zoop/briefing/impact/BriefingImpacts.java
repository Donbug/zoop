package com.zoop.briefing.impact;

import java.time.Instant;
import java.util.List;
import com.zoop.common.response.Metadata;

/** Read projection of S3 verifier quote effects, never a price forecast or a producer-proposal rationale. */
public record BriefingImpacts(String roundId, String eventId, String graphVersion, Instant dataAsOf,
        String status, String reason, List<CompanyImpact> companies, Metadata metadata, ReviewContext reviewContext) {
    public BriefingImpacts(String roundId, String eventId, String graphVersion, Instant dataAsOf,
            String status, String reason, List<CompanyImpact> companies, Metadata metadata) {
        this(roundId, eventId, graphVersion, dataAsOf, status, reason, companies, metadata, null);
    }
    public record ReviewContext(String mode, Instant assessedAt, String inputScope,
            String generationModel, String verifierModel, String resultVersion, String citationPolicy) {
        public ReviewContext(String mode, Instant assessedAt, String inputScope,
                String generationModel, String verifierModel, String resultVersion) {
            this(mode,assessedAt,inputScope,generationModel,verifierModel,resultVersion,null);
        }
    }
    public record CompanyImpact(String companyId, String companyName, String status, String reason,
            List<Assessment> assessments) { }
    public record Assessment(String id, String relationId, String status, String label, Provenance provenance,
            List<EffectEvidence> evidence, List<FactEvidence> facts, EvidencePlan evidencePlan, SupplementalReview supplementalReview) {
        public Assessment(String id, String relationId, String status, String label, Provenance provenance,
                List<EffectEvidence> evidence, List<FactEvidence> facts, EvidencePlan evidencePlan) {
            this(id,relationId,status,label,provenance,evidence,facts,evidencePlan,null);
        }
        public Assessment(String id, String relationId, String status, String label, Provenance provenance,
                List<EffectEvidence> evidence) { this(id,relationId,status,label,provenance,evidence,List.of(),null); }
        public Assessment(String id, String relationId, String status, String label, Provenance provenance,
                List<EffectEvidence> evidence, List<FactEvidence> facts) { this(id,relationId,status,label,provenance,evidence,facts,null); }
    }
    public record Provenance(String sourceKind, String executionMode, String recordingKind) { }
    /** A later verifier result over additional sources. Original assessment remains immutable. */
    public record SupplementalReview(String mode, Instant assessedAt, String previousLabel, String label,
            String targetVerdict, String verifierModel, String summary, String limitations,
            List<ReviewFact> confirmedFacts, List<EffectEvidence> evidence, String resultVersion,
            boolean historicalVersionVerified) { }
    public record ReviewFact(String text, List<String> evidenceIds) { }
    public record EffectEvidence(String id, String effect, String quote, String articleId, String articleVersion,
            String title, String url, Instant publishedAt, long start, long end) { }
    /** Literal source context only; never a directionally verified business effect. */
    public record FactEvidence(String id, String quote, String articleId, String articleVersion,
            String title, String url, Instant publishedAt, long start, long end) { }
    public record EvidencePlan(String status, Instant preparedAt, String reason,
            List<SupportingFact> existingEvidence, List<CollectionNeed> collectionNeeds, ResearchSupplement research) {
        public EvidencePlan(String status, Instant preparedAt, String reason,
                List<SupportingFact> existingEvidence, List<CollectionNeed> collectionNeeds) {
            this(status,preparedAt,reason,existingEvidence,collectionNeeds,null);
        }
    }
    /** Later editorial primary-source links, separate from native AI verification and publication evidence. */
    public record ResearchSupplement(String status, Instant linkedAt, List<LinkedSource> sources, PublicationTimeCheck timeCheck) { }
    public record LinkedSource(String id, String companyId, String title, String url, Instant publishedAt,
            String timeBasis, String summary, String limitations, String excerpt, String transport,
            String textSha256, boolean historicalVersionVerified) { }
    public record PublicationTimeCheck(String status, String summary, String limitation,
            Instant storedPublishedAt, Instant distributionPublishedAt, String storedUrl, String distributionUrl) { }
    public record SupportingFact(String scope, String note, FactEvidence source) { }
    public record CollectionNeed(String kind, String what, String why, String preferredSource) { }
}
