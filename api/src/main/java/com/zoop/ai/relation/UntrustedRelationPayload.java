package com.zoop.ai.relation;

import java.util.List;
import java.util.Objects;

/**
 * The S3 relation and impact candidates of one ready job ({@code RelationJobContent}) as the AI service delivered them.
 *
 * <p><b>Untrusted.</b> The client verified only that it is a JSON object whose {@code jobId} and {@code inputDigest} equal the
 * requested job's status, and read one {@link Candidate} (id, source version, source revision) per relation, requiring that every
 * relation's {@code sourceVersion} equals the job's {@code inputDigest}. Everything else (relations, directions, impact labels,
 * citations, eligibility) is model or rule output with {@code approved=false} that a later importer must validate with its own
 * strict reader against its own immutable documents and current source rights. {@code toString} never prints the content.
 */
public final class UntrustedRelationPayload {
    private final String jobId;
    private final String inputDigest;
    private final String json;
    private final List<Candidate> candidates;

    public UntrustedRelationPayload(String jobId, String inputDigest, String json, List<Candidate> candidates) {
        this.jobId = Objects.requireNonNull(jobId, "jobId");
        this.inputDigest = Objects.requireNonNull(inputDigest, "inputDigest");
        this.json = Objects.requireNonNull(json, "json");
        this.candidates = List.copyOf(candidates);
    }

    /**
     * The AI source identity of one relation candidate: what a review must expect.
     *
     * @param sourceVersion the job's {@code inputDigest}
     * @param sourceRevision the candidate's runtime event-chain revision as a decimal string ({@code 0} when it has no event yet)
     */
    public record Candidate(String relationCandidateId, String sourceVersion, String sourceRevision) {
    }

    public String jobId() {
        return jobId;
    }

    public String inputDigest() {
        return inputDigest;
    }

    /** The source identities in the order the service delivered them. */
    public List<Candidate> candidates() {
        return candidates;
    }

    /** The content as compact JSON text. Parse it with the caller's own strict, typed reader; do not trust any field. */
    public String untrustedJson() {
        return json;
    }

    @Override
    public String toString() {
        return "UntrustedRelationPayload[jobId=" + jobId + ", candidates=" + candidates.size() + ", bytes=" + json.length() + "]";
    }
}
