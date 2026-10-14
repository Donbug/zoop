package com.zoop.document.importer;

/** Source of one fresh S2-1 export document. */
public interface IngestionExporter {

    /**
     * Runs the export for exactly this observation and returns the CLI's raw JSON bytes (unvalidated).
     *
     * @throws com.zoop.document.DocumentImportException {@code ingestion_export_failed} when the CLI refused (for example
     *         the grant is no longer valid) or {@code ingestion_export_unavailable} when it could not run or answer
     */
    byte[] export(Observation observation);
}
