package com.zoop.document.evidence.service;

import java.nio.file.Path;

import com.zoop.common.exception.CustomException;
import com.zoop.common.exception.ErrorCode;
import com.zoop.document.importer.SourceRegistry;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

/**
 * The operator's S2-1 source registry ({@code zoop-ingestion-s2-1}) as the graph evidence read sees it: the same file the handoff
 * import checks, read fresh on every call and never cached. Unset, unreadable or invalid is {@code SOURCE_UNAVAILABLE} (503),
 * never an open or empty registry. The log line carries the failure code only: no path, no registry content.
 */
public final class DocumentReadSources {
    private static final Logger log = LoggerFactory.getLogger(DocumentReadSources.class);

    private final Path path;

    /** @param path the registry file, or {@code null} when {@code zoop.document-read.ingestion-sources} is not set */
    public DocumentReadSources(Path path) {
        this.path = path;
    }

    public SourceRegistry registry(String requestId) {
        if (path == null) {
            log.warn("Document read ingestion sources are not configured (requestId={})", requestId);
            throw new CustomException(ErrorCode.SOURCE_UNAVAILABLE);
        }
        try {
            return SourceRegistry.read(path);
        } catch (SourceRegistry.Invalid error) {
            log.warn("Document read ingestion source registry unavailable (code={}, requestId={})", error.code(), requestId);
            throw new CustomException(ErrorCode.SOURCE_UNAVAILABLE);
        }
    }
}
