package com.zoop.graph.exclusion;

import java.util.List;

/**
 * One run of the exclusion command: an {@code exclude} from an AI exposure report, or an explicit {@code lift}. {@code requestId}
 * names the command and {@code requestSha256} is the SHA-256 of the canonical request: a re-run of a recorded command returns its
 * stored result and never changes anything again.
 */
public sealed interface ExclusionRequest {
    String requestId();

    String requestSha256();

    String operator();

    String reason();

    /** Excludes what the report proposes, per handoff, in the graph version imported from that handoff. */
    record Exclude(String requestId, String requestSha256, String operator, String reason, Report report)
            implements ExclusionRequest {
    }

    /**
     * Lifts these targets of one version: the only way an exclusion ends (an empty or smaller report never lifts). Refused when a
     * target changed after {@code expectedRevision}, the exclusion revision the operator decided on.
     */
    record Lift(String requestId, String requestSha256, String operator, String reason, String graphVersionId,
            long expectedRevision, List<Target> targets) implements ExclusionRequest {
        public Lift {
            targets = List.copyOf(targets);
        }
    }

    /**
     * A parsed {@code zoop-handoff-exposure-1} report: its {@code cause}, the SHA-256 of its canonical JSON (kept with the change)
     * and the handoffs it selected.
     */
    record Report(String cause, String sha256, List<Handoff> handoffs) {
        public Report {
            handoffs = List.copyOf(handoffs);
        }
    }

    /**
     * One selected handoff with the pins the app must find in the receipt of its imported version and the public ids the report
     * proposes to exclude there (empty unless {@code exposed}).
     */
    record Handoff(String handoffId, String manifestDigest, String bundleDigest, String contentDigest, boolean exposed,
            List<Target> targets) {
        public Handoff {
            targets = List.copyOf(targets);
        }
    }

    /** One exclusion target. {@code articleVersion} is the article's version for {@code article}, {@code ""} otherwise. */
    record Target(String kind, String id, String articleVersion) {
        public static final List<String> KINDS = List.of("issue", "relation", "evidence", "article");

        public Target {
            if (!KINDS.contains(kind) || id == null || articleVersion == null
                    || "article".equals(kind) == articleVersion.isEmpty()) {
                throw new IllegalArgumentException("target");
            }
        }
    }
}
