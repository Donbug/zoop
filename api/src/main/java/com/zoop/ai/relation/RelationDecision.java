package com.zoop.ai.relation;

/** The two review decisions the service records on a HOLD relation. {@code ALLOW} is the operator's FINAL approval (no revalidation, no model call), {@code REJECT} an exclusion; neither one publishes. */
public enum RelationDecision {
    ALLOW, REJECT
}
