package com.zoop.chat.tool;

import java.util.List;

/**
 * One pair of a path read ({@code graph.path.read}): how {@code fromId} connects to {@code toId}. {@code found} has the
 * steps in path order; {@code none} was proven unconnected within the hop limit; {@code cut} reached the hop limit, so a
 * longer connection may exist and it is never "none". A step is one stored display edge with its stored direction, relation
 * type, display role and the evidence passed on for it.
 */
public record ChatToolPath(String fromId, String toId, String status, List<Step> steps) {
    public static final String FOUND = "found";
    public static final String NONE = "none";
    public static final String CUT = "cut";

    public record Step(String edgeId, String sourceId, String targetId, String relation, String role,
            List<String> evidenceIds) {
        public Step {
            evidenceIds = List.copyOf(evidenceIds);
        }
    }

    public ChatToolPath {
        steps = List.copyOf(steps);
        if (FOUND.equals(status) == steps.isEmpty()) throw new IllegalArgumentException("a found path has steps, others none");
    }
}
