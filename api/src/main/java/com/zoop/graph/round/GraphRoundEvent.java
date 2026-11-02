package com.zoop.graph.round;

import java.time.Instant;
import java.util.Optional;

import tools.jackson.databind.JsonNode;

/**
 * One line of a round's timeline ({@code graph_round_events}, written once).
 *
 * @param outcome   {@code advanced}, {@code waiting}, {@code failed}, {@code retried} or {@code skipped}
 * @param code      the answer's code (failure or wait reason), when there is one
 * @param requestId the {@code X-Request-ID} of the external call this line records, to match the AI side's log
 * @param detail    codes and digests of the answer only; never a path, a body or a secret
 */
public record GraphRoundEvent(long id, String roundId, Instant at, GraphRoundStage stage, Outcome outcome,
        Optional<String> code, Optional<String> requestId, Optional<JsonNode> detail) {

    public enum Outcome {
        ADVANCED("advanced"), WAITING("waiting"), FAILED("failed"), RETRIED("retried"), SKIPPED("skipped");

        private final String wire;

        Outcome(String wire) {
            this.wire = wire;
        }

        public String wire() {
            return wire;
        }

        public static Outcome parse(String wire) {
            for (Outcome outcome : values()) {
                if (outcome.wire.equals(wire)) return outcome;
            }
            throw new IllegalArgumentException("unknown round event outcome");
        }
    }
}
