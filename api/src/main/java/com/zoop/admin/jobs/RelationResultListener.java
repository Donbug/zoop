package com.zoop.admin.jobs;

import com.zoop.ai.relation.RelationUpstream;
import com.zoop.ai.relation.UntrustedRelationPayload;

/**
 * Told about every S3 result the worker fetched and recorded. It runs after the stage observation is committed and outside any
 * repository transaction; a failure is the listener's own and never changes the job (the worker logs it and moves on).
 */
@FunctionalInterface
public interface RelationResultListener {
    /**
     * @param s2ResultSha256 the content hash of the S2 result this unit recorded before the S3 job ran, so a listener that reads
     *                       the S2 result again can tell it is the same content
     */
    void relationResultFetched(RelationUpstream upstream, String s2ResultSha256, UntrustedRelationPayload payload);
}
