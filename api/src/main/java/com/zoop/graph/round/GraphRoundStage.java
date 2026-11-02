package com.zoop.graph.round;

import java.util.Locale;

/**
 * Where a round stands. The order is the one the scheduler advances through; {@link #IMPORTED}, {@link #SKIPPED} and
 * {@link #FAILED} are terminal. A failed round keeps its round id: a retry resumes it from the stage it stopped at, because the
 * AI side keys its own idempotency on that id and asks that an unknown outcome is never dropped and re-sent as a new round.
 */
public enum GraphRoundStage {
    /** The slot row exists; nothing has been asked of the AI side yet. */
    SCHEDULED("scheduled"),
    /** R1 accepted: the AI side runs tick → plan-round for this round. */
    RUN_REQUESTED("run_requested"),
    /** R2: a plan (id and digest) exists for the round. */
    PLAN_READY("plan_ready"),
    /** R3: the app's analyze_plan job for the plan is queued or running. */
    ANALYSIS_QUEUED("analysis_queued"),
    /** R4: the analyze_plan job ended in {@code ai_processing_handoff}. */
    ANALYSIS_DONE("analysis_done"),
    /** R5 accepted: the AI side freezes the handoff. */
    FREEZE_REQUESTED("freeze_requested"),
    /** R6: the handoff id and its two digests are known. */
    HANDOFF_READY("handoff_ready"),
    /** R7: the handoff is staged as an inactive version (or the same pins were staged before: {@code unchanged}). Activation is the auto-activation scheduler's. */
    IMPORTED("imported"),
    /** No new material in this slot, or a newer round was imported first: nothing to publish, not a failure. */
    SKIPPED("skipped"),
    /** The round stopped with a failure code; a retry resumes it. */
    FAILED("failed");

    private final String wire;

    GraphRoundStage(String wire) {
        this.wire = wire;
    }

    public String wire() {
        return wire;
    }

    public boolean terminal() {
        return this == IMPORTED || this == SKIPPED || this == FAILED;
    }

    public static GraphRoundStage parse(String wire) {
        for (GraphRoundStage stage : values()) {
            if (stage.wire.equals(wire)) return stage;
        }
        throw new IllegalArgumentException("unknown round stage: " + wire.toLowerCase(Locale.ROOT));
    }
}
