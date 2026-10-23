package com.zoop.chat.tool;

/**
 * A read-only adapter behind one capability. It reads only within {@code scope}; it never writes, never accepts a member id
 * from the request and never turns an outage into an empty result: a source it cannot read throws
 * {@link ChatToolUnavailable}.
 */
public interface ChatTool {
    ChatCapability capability();

    ChatToolOutput read(ChatToolScope scope, ChatToolRequest request);
}
