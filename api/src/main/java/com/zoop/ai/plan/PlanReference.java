package com.zoop.ai.plan;

import java.util.regex.Pattern;

import com.zoop.ai.PipelineJob;

/** An exact installed plan reference, never a path or an execution/source/budget grant. */
public record PlanReference(String planId, String planDigest) {
    public static final String SCHEMA_VERSION = "zoop-ai-plan-admission-1";
    public static final Pattern PLAN_ID = Pattern.compile("s2plan-[0-9a-f]{64}");

    public PlanReference {
        if (planId == null || !PLAN_ID.matcher(planId).matches()) {
            throw new IllegalArgumentException("planId must be an exact S2 plan ID");
        }
        PipelineJob.requireDigest("planDigest", planDigest);
    }
}
