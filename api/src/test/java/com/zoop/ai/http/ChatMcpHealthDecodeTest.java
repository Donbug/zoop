package com.zoop.ai.http;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertNull;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.junit.jupiter.api.Assertions.assertTrue;

import com.zoop.ai.chat.ChatMcpHealth;
import com.zoop.ai.http.WireJson.Malformed;
import org.junit.jupiter.api.Test;

/** Strict health decoding without HTTP or a listening socket. */
class ChatMcpHealthDecodeTest {
    @Test
    void decodesReachableAndEveryClosedUnreachableReason() {
        ChatMcpHealth reachable = decode("reachable", "null");
        assertTrue(reachable.reachable());
        assertNull(reachable.reason());
        assertEquals(ChatMcpHealth.Reason.TIMEOUT, decode("unreachable", "\"mcp_timeout\"").reason());
        assertEquals(ChatMcpHealth.Reason.CONNECT_FAILED, decode("unreachable", "\"mcp_connect_failed\"").reason());
        assertEquals(ChatMcpHealth.Reason.UNAVAILABLE, decode("unreachable", "\"mcp_unavailable\"").reason());
        ChatMcpHealth unexpected = decode("unreachable", "\"mcp_status_unexpected\"");
        assertFalse(unexpected.reachable());
        assertEquals(ChatMcpHealth.Reason.STATUS_UNEXPECTED, unexpected.reason());
    }

    @Test
    void rejectsContradictoryOrOpenHealthAnswers() {
        assertThrows(Malformed.class, () -> decode("reachable", "\"mcp_timeout\""));
        assertThrows(Malformed.class, () -> decode("unreachable", "null"));
        assertThrows(Malformed.class, () -> decode("unreachable", "\"other\""));
        assertThrows(Malformed.class, () -> HttpChatStageClient.decodeHealth(WireJson.parse(
                "{\"schemaVersion\":\"other\",\"mcp\":\"reachable\",\"reason\":null}", "body")));
    }

    private static ChatMcpHealth decode(String mcp, String reason) {
        return HttpChatStageClient.decodeHealth(WireJson.parse("{\"schemaVersion\":\"zoop-ai-chat-4\",\"mcp\":\""
                + mcp + "\",\"reason\":" + reason + "}", "body"));
    }
}
