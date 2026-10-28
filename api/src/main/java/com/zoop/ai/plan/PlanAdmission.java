package com.zoop.ai.plan;

import java.time.Instant;
import java.util.Objects;
import java.util.Optional;

import com.zoop.ai.PipelineJob;

/** Admission-policy authority only: active does not establish source rights, readiness, model budget or publication. */
public record PlanAdmission(String admissionId, Instant acceptedAt, long policyRevision, String policyDigest,
                            PlanManifest manifest, Authority authority) {
    private static final java.util.regex.Pattern REASON = java.util.regex.Pattern.compile("[a-z][a-z0-9_]{0,79}");

    public PlanAdmission {
        Objects.requireNonNull(manifest, "manifest");
        if (!PlanIdentity.admissionId(manifest.principal(), manifest.reference()).equals(admissionId)) {
            throw new IllegalArgumentException("admission identity mismatch");
        }
        Objects.requireNonNull(acceptedAt, "acceptedAt");
        if (policyRevision <= 0) {
            throw new IllegalArgumentException("policyRevision must be positive");
        }
        PipelineJob.requireDigest("policyDigest", policyDigest);
        Objects.requireNonNull(authority, "authority");
    }

    public enum State { ACTIVE, INACTIVE }

    public record Authority(State state, Optional<String> reason) {
        public Authority {
            Objects.requireNonNull(state, "state");
            Objects.requireNonNull(reason, "reason");
            if ((state == State.INACTIVE) != reason.isPresent()
                    || reason.filter(value -> !REASON.matcher(value).matches()).isPresent()) {
                throw new IllegalArgumentException("authority reason is required exactly when inactive");
            }
        }
    }
}
