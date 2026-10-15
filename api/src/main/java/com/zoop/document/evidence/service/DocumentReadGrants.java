package com.zoop.document.evidence.service;

import java.nio.file.Path;

import com.zoop.common.exception.CustomException;
import com.zoop.common.exception.ErrorCode;
import com.zoop.document.analysis.AnalysisException;
import com.zoop.document.analysis.GrantRegistry;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

/**
 * The operator's flat S1 grant registry as the web read side sees it: read fresh from the configured file on every call, never
 * cached. Unset, unreadable, too large, schema-invalid or revision-conflicting is {@code SOURCE_UNAVAILABLE} (503), never an
 * open or an empty registry. The log line carries the failure code only: no path, no registry content.
 */
public final class DocumentReadGrants {
    private static final Logger log = LoggerFactory.getLogger(DocumentReadGrants.class);

    private final Path path;

    /** @param path the registry file, or {@code null} when {@code zoop.document-read.grants} is not set */
    public DocumentReadGrants(Path path) {
        this.path = path;
    }

    public GrantRegistry registry(String requestId) {
        if (path == null) {
            log.warn("Document read grants are not configured (requestId={})", requestId);
            throw new CustomException(ErrorCode.SOURCE_UNAVAILABLE);
        }
        try {
            return GrantRegistry.read(path);
        } catch (AnalysisException error) {
            log.warn("Document read grant registry unavailable (code={}, requestId={})", error.details(), requestId);
            throw new CustomException(ErrorCode.SOURCE_UNAVAILABLE);
        }
    }
}
