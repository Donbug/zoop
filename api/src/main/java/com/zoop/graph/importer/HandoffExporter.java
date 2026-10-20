package com.zoop.graph.importer;

/** Source of one fresh, currently valid handoff export envelope. */
public interface HandoffExporter {

    /**
     * Runs the export for exactly this handoff and returns the CLI's raw JSON bytes (unvalidated).
     *
     * @throws GraphHandoffException {@code handoff_refused} (the CLI's structured error), {@code handoff_withheld} (the
     *         handoff is not deliverable under current authority; there is no content) or {@code handoff_export_unavailable}
     *         when it could not run or answer
     */
    byte[] export(String handoffId);
}
