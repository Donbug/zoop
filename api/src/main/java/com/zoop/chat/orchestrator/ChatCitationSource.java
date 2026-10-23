package com.zoop.chat.orchestrator;

import com.zoop.chat.dto.Citation;
import java.time.Instant;
import java.util.Optional;

/**
 * Builds an article citation from the evidence record itself: quote, code-point offsets, article version and source, as the
 * public evidence read serves it at the job's pinned graph version and asOf. A model never supplies citation text.
 */
public interface ChatCitationSource {
    /**
     * The citation, or empty when the evidence read refuses it now. Throws {@link com.zoop.chat.tool.ChatToolUnavailable}
     * when it cannot be checked.
     */
    Optional<Citation> cite(String evidenceId, String graphVersion, Instant asOf, String traceId);
}
