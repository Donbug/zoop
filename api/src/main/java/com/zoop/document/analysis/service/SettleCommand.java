package com.zoop.document.analysis.service;

import java.time.Instant;
import java.util.List;
import java.util.Objects;

import com.zoop.document.analysis.repository.ExecutionRow;

/**
 * One terminal settlement of a pending analysis. {@code artifacts} are files that are already stored (receipts and, only for
 * {@code available}, the result, verifier and exact receipt); {@code executions} are the attempts to count once;
 * {@code evidence} and {@code available} are set exactly for a requested {@code available} outcome. {@code currentAuthority}
 * rechecks local application authority after the database locks have been acquired; a denial downgrades that outcome to
 * {@code withheld}. {@code model}, {@code promptVersion} and {@code reasoningEffort} are those of the generation receipt, or
 * null when the settlement has none.
 */
public record SettleCommand(String analysisId, String aiJobId, String status, String reason, String model,
        String promptVersion, String reasoningEffort, List<ArtifactFile> artifacts, List<ExecutionRow> executions,
        List<EvidenceDraft> evidence, AvailableFields available, CurrentAuthority currentAuthority) {

    public SettleCommand {
        artifacts = List.copyOf(artifacts);
        executions = List.copyOf(executions);
        evidence = List.copyOf(evidence);
        if (available != null) {
            Objects.requireNonNull(currentAuthority, "currentAuthority");
        }
    }

    /** A bounded local check: implementations must not perform model or other external network calls. */
    @FunctionalInterface
    public interface CurrentAuthority {
        /** Returns a stable denial code, or null when the current grant still authorizes this source at {@code now}. */
        String denial(String sourceId, Instant now);
    }
}
