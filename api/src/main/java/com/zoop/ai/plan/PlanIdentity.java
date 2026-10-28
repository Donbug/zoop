package com.zoop.ai.plan;

import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.security.NoSuchAlgorithmException;
import java.util.HexFormat;
import java.util.regex.Pattern;

import com.zoop.ai.PipelineJob;

/** Exact canonical preimages shared with the service; no revision or recovery-generated identity. */
public final class PlanIdentity {
    public static final Pattern PRINCIPAL = Pattern.compile("[a-z][a-z0-9-]{0,62}");

    private PlanIdentity() {
    }

    public static String admissionId(String principal, PlanReference reference) {
        if (principal == null || !PRINCIPAL.matcher(principal).matches()) {
            throw new IllegalArgumentException("principal must be a service principal name");
        }
        return "pa-" + sha256("{\"format\":\"zoop-plan-admission-identity-1\",\"planDigest\":\"" + reference.planDigest()
                + "\",\"planId\":\"" + reference.planId() + "\",\"principal\":\"" + principal + "\"}");
    }

    public static String relationJobId(PlanReference reference, String jobId, String inputDigest) {
        PipelineJob.requireId("jobId", jobId);
        PipelineJob.requireDigest("inputDigest", inputDigest);
        return "s3p-" + sha256("{\"format\":\"zoop-plan-admission-relation-job-1\",\"planDigest\":\"" + reference.planDigest()
                + "\",\"planId\":\"" + reference.planId() + "\",\"upstream\":{\"inputDigest\":\"" + inputDigest
                + "\",\"jobId\":\"" + jobId + "\"}}");
    }

    public static String sha256(String canonicalJson) {
        try {
            return HexFormat.of().formatHex(MessageDigest.getInstance("SHA-256").digest(canonicalJson.getBytes(StandardCharsets.UTF_8)));
        } catch (NoSuchAlgorithmException impossible) {
            throw new IllegalStateException("SHA-256 unavailable");
        }
    }
}
