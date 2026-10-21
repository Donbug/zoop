package com.zoop.chat.executor;

import org.springframework.beans.factory.ObjectProvider;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Component;

/**
 * Refuses to start with question intake on but no {@link ChatEngine}: accepted jobs would wait in {@code queued} forever.
 */
@Component
public class ChatEngineRequirement {
    public ChatEngineRequirement(ObjectProvider<ChatEngine> engines,
            @Value("${zoop.chat.questions-enabled:false}") boolean questionsEnabled) {
        if (questionsEnabled && engines.getIfAvailable() == null) {
            throw new IllegalStateException(
                    "zoop.chat.questions-enabled=true needs a ChatEngine; none is registered, so no job would ever run");
        }
    }
}
