package com.zoop.ai.chat;

/**
 * The chatbot model stage transport ({@code POST /internal/v1/chat-stages/{stage}}, contract {@code zoop-ai-chat-6}): one
 * synchronous stage per call. The invocation id and exact persisted allocation identify its single-send outcome.
 *
 * <p>Outcomes: a returned {@link ChatStageReply} is the stage outcome (succeeded, or failed with whether a request was sent and
 * whether its fate is unknown). A thrown {@link com.zoop.ai.AiClientException} is a transport-level answer; its
 * {@code requestMaybeProcessed()} says whether the stage may have sent a model request (a 502/504 {@code stage_outcome_unknown},
 * a timeout or a lost connection), in which case the invocation must never be sent again.
 */
public interface ChatStageClient {
    ChatStageReply invoke(ChatStageCall call);

    ChatRuntimeCapabilities capabilities();

    void requireTimeout(java.time.Duration required);
}
