package com.zoop.ai.plan;

/**
 * One bounded HTTP request per method, no retries or execution. After an ambiguous admit, query this same reference; never
 * mint another identity. There is deliberately no policy-control method or app-side policy configuration.
 */
public interface PlanAdmissionClient {
    PlanAdmission admit(PlanReference reference);

    PlanAdmission status(PlanReference reference);
}
