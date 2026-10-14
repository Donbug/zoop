package com.zoop.ai.relation;

import java.util.regex.Pattern;

import com.zoop.ai.PipelineJob;

/**
 * The S2 job an S3 job is built over: its id and input digest. Naming it grants nothing: the service refuses with
 * {@code 403 upstream_not_allowed} unless the operator's server-side allowlist lists exactly this pair for the calling principal,
 * and the same allowlist is read again on every submit, result, review and revalidation.
 */
public record RelationUpstream(String jobId, String inputDigest) {
    /** The S2 job id as the service accepts it (wider than the app's own job ids: it may contain {@code :}). */
    public static final Pattern JOB_ID = Pattern.compile("[A-Za-z0-9._:-]{1,200}");

    public RelationUpstream {
        if (jobId == null || !JOB_ID.matcher(jobId).matches()) {
            throw new IllegalArgumentException("upstream.jobId must match " + JOB_ID.pattern());
        }
        PipelineJob.requireDigest("upstream.inputDigest", inputDigest);
    }
}
