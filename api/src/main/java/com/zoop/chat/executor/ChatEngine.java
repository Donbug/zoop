package com.zoop.chat.executor;

/**
 * The orchestrator seam (AI chatbot implementation plan, stages 2 to 5): turns one claimed run into a verified result or a
 * classified failure. The executor owns the job state; an engine only reports progress through {@link ChatRunControl} and
 * returns an outcome. It never writes {@code chat_jobs} itself.
 *
 * <p>No production engine exists yet. While none is registered, the executor claims nothing and question intake must stay
 * off ({@code zoop.chat.questions-enabled}); startup refuses the opposite.
 */
public interface ChatEngine {
    /**
     * Answers one run. Throwing {@link ChatRunSuperseded} (from the control) ends the run silently; any other exception is
     * an unclassified failure that is never rerun.
     */
    ChatEngineOutcome answer(ChatRun run, ChatRunControl control);
}
