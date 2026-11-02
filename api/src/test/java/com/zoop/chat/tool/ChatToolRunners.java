package com.zoop.chat.tool;

import java.time.Duration;

/** Runners for tests of the flow: a machine's speed must not decide a case, so a call's time limit stays out of the way. */
public final class ChatToolRunners {
    private static final Duration AMPLE = Duration.ofSeconds(60);

    private ChatToolRunners() {
    }

    public static ChatToolRunner withAmpleTime(ChatToolRegistry registry) {
        return new ChatToolRunner(registry, AMPLE, AMPLE, AMPLE, ChatToolRunner.RECORD_GRACE, ChatToolRunner.MAX_IN_FLIGHT);
    }
}
