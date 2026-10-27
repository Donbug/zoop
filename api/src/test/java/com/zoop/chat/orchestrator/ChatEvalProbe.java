package com.zoop.chat.orchestrator;

import java.util.List;

/** What the chat evaluation set (com.zoop.chat.model.ChatEvalSetTest) reads of package-private orchestrator decisions. */
public final class ChatEvalProbe {
    private ChatEvalProbe() {
    }

    /** The first deterministic check the answer fails, or null when it passes. */
    public static String failedCheck(List<ChatBranchContext.Branch> branches, ChatGeneratedAnswer answer) {
        return ChatAnswerCheck.check(branches, answer).failedCheck();
    }
}
