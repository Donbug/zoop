package com.zoop.ai.plan;

import java.util.HashSet;
import java.util.List;
import java.util.Objects;

import com.zoop.ai.PipelineJob;
import com.zoop.ai.extraction.ExtractionSubmission;
import com.zoop.ai.relation.RelationSubmission;

/** Immutable reference-only manifest. Order is the verified plan order, not a client-generated sort. */
public record PlanManifest(PlanReference reference, String receiptSha256, String principal, Round round,
                           PipelineJob.Provenance provenance, List<Unit> units, String manifestDigest) {
    public static final String SCHEMA_VERSION = "zoop-ai-plan-manifest-1";

    public PlanManifest {
        Objects.requireNonNull(reference, "reference");
        PipelineJob.requireDigest("receiptSha256", receiptSha256);
        if (principal == null || !PlanIdentity.PRINCIPAL.matcher(principal).matches()) {
            throw new IllegalArgumentException("principal must be a service principal name");
        }
        Objects.requireNonNull(round, "round");
        Objects.requireNonNull(provenance, "provenance");
        Objects.requireNonNull(provenance.sourceKind(), "sourceKind");
        Objects.requireNonNull(provenance.executionMode(), "executionMode");
        units = List.copyOf(units);
        var keys = new HashSet<String>();
        var relationIds = new HashSet<String>();
        for (Unit unit : units) {
            if (!keys.add(unit.unitKey()) || !relationIds.add(unit.relationSubmit().jobId())
                    || unit.extractionSubmit().executionMode() != provenance.executionMode()
                    || unit.relationSubmit().executionMode() != provenance.executionMode()
                    || unit.relationSubmit().sourceKind() != provenance.sourceKind()
                    || !unit.relationSubmit().jobId().equals(PlanIdentity.relationJobId(reference, unit.unitKey(), unit.extractionInputDigest()))) {
                throw new IllegalArgumentException("manifest unit identity or provenance mismatch");
            }
        }
        PipelineJob.requireDigest("manifestDigest", manifestDigest);
    }

    public record Round(String sourceId, String roundId, String ingestionInputDigest) {
        public Round {
            if (sourceId == null || sourceId.isEmpty() || sourceId.codePointCount(0, sourceId.length()) > 200
                    || roundId == null || roundId.isEmpty() || roundId.codePointCount(0, roundId.length()) > 200) {
                throw new IllegalArgumentException("round and source identities must contain 1-200 Unicode characters");
            }
            PipelineJob.requireDigest("ingestionInputDigest", ingestionInputDigest);
        }
    }

    public record Unit(String unitKey, ExtractionSubmission extractionSubmit, String extractionInputDigest,
                       RelationSubmission relationSubmit) {
        public Unit {
            PipelineJob.requireId("unitKey", unitKey);
            Objects.requireNonNull(extractionSubmit, "extractionSubmit");
            Objects.requireNonNull(relationSubmit, "relationSubmit");
            PipelineJob.requireDigest("extractionInputDigest", extractionInputDigest);
            if (!unitKey.equals(extractionSubmit.jobId()) || !unitKey.equals(relationSubmit.upstream().jobId())
                    || !extractionInputDigest.equals(relationSubmit.upstream().inputDigest())) {
                throw new IllegalArgumentException("unit references must bind the same S2 input");
            }
        }
    }
}
