package com.zoop.chat.tool;

/** The data a tool reads cannot be read now (no frozen graph, an unavailable version or store); never "nothing found". */
public final class ChatToolUnavailable extends RuntimeException {
    public ChatToolUnavailable(String message) {
        super(message);
    }

    public ChatToolUnavailable(String message, Throwable cause) {
        super(message, cause);
    }
}
