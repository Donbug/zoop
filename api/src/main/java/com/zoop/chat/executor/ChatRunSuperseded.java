package com.zoop.chat.executor;

/** The run no longer owns its job (cancelled, lease expired, or replaced); whatever it computed is discarded. */
public final class ChatRunSuperseded extends RuntimeException {
    public ChatRunSuperseded() {
        super("chat run superseded", null, false, false);
    }
}
