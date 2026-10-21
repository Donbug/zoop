package com.zoop.chat.executor;

import com.zoop.chat.dto.ChatResult;
import tools.jackson.databind.JsonNode;

/** What an engine returns: a verified result to store, or a classified failure. */
public sealed interface ChatEngineOutcome {
    /**
     * A result that passed the engine's verification. The executor replaces {@code messageId} and stores it as is.
     * {@code routeSummary} is the internal route record (null when the engine keeps none); free-form reasoning never goes there.
     */
    record Completed(ChatResult result, JsonNode routeSummary) implements ChatEngineOutcome { }

    /**
     * A failure by {@code ChatFailure.kind} and {@code reason} code (ZOOP-AIG-001 6.3.3). {@code rerunnable} says the provider
     * did not process the request or answered with a confirmed failure; the executor still decides {@code retry}.
     */
    record Failed(String kind, String reason, boolean rerunnable) implements ChatEngineOutcome { }
}
