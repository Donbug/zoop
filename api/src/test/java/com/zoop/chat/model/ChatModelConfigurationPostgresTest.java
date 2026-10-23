package com.zoop.chat.model;

import static org.junit.jupiter.api.Assertions.assertInstanceOf;

import com.zoop.chat.executor.ChatEngine;
import com.zoop.chat.orchestrator.OrchestratedChatEngine;
import org.junit.jupiter.api.Tag;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.condition.EnabledIfEnvironmentVariable;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.context.SpringBootTest;

/**
 * With the chat client enabled the application registers the orchestrated engine, so question intake can be on. The client
 * points at a closed loopback port: nothing is called while the context starts.
 */
@SpringBootTest(properties = {
        "ZOOP_AUTH_CSRF_ACTIVE_KEY_ID=test",
        "ZOOP_AUTH_CSRF_KEYS=test=AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA",
        "zoop.chat.questions-enabled=true",
        "zoop.chat.executor.enabled=false",
        "zoop.ai.chat-client.enabled=true",
        "zoop.ai.chat-client.base-url=http://127.0.0.1:9",
        "zoop.ai.chat-client.token=test-token-0123456789abcdefghijklmnopqrstuvwxyz",
        "zoop.ai.chat-client.mode=replay"
})
@EnabledIfEnvironmentVariable(named = "DB_URL", matches = "jdbc:postgresql:.*")
@Tag("auth-postgres")
class ChatModelConfigurationPostgresTest {
    @Autowired ChatEngine engine;

    @Test
    void theEnabledChatClientRegistersTheOrchestratedEngine() {
        assertInstanceOf(OrchestratedChatEngine.class, engine);
    }
}
