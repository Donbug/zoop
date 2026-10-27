package com.zoop.ai.handoff;

import java.util.List;

import tools.jackson.databind.JsonNode;

/**
 * {@code queryGraphHandoffExposure} (scope {@code handoff.exposure}): which public ids of the selected fixed handoffs a changed
 * document, source, grant or S3 relation touches. The answer is a proposal only: the AI service changes nothing and the app decides
 * and records any exclusion (api/docs/GRAPH_READ_HANDOFF.md "공개 영향 ID 인계").
 */
public interface HandoffExposureClient {
    /** At most this many handoffs per query (the contract's {@code maxItems}). */
    int MAX_HANDOFFS = 20;

    /**
     * @param handoffIds 1 to {@link #MAX_HANDOFFS} distinct handoff ids
     * @param changed    the {@code DocumentChange}/{@code SourceChange}/{@code GrantChange}/{@code RelationChange} object
     * @return the {@code ExposureReport} object of the answer, untrusted: the caller validates it as it validates a report file
     */
    JsonNode exposure(List<String> handoffIds, JsonNode changed);
}
