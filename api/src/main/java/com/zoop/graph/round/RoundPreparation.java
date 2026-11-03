package com.zoop.graph.round;

import java.time.Instant;

/**
 * Work the scheduler does once at the end of a pass, outside every round's lease (#55 PR-P3: the automatic preparation of an
 * inactive candidate from what the rounds imported). It never changes a round: an import stays {@code imported} whatever happens
 * here, and a failure only waits for the next pass.
 */
public interface RoundPreparation {
    RoundPreparation NONE = now -> { };

    void afterPass(Instant now);
}
