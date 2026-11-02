package com.zoop.chat.service;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertTrue;

import com.zoop.chat.tool.ChatCapability;
import com.zoop.chat.tool.ChatToolRegistry;
import org.junit.jupiter.api.Tag;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.condition.EnabledIfEnvironmentVariable;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.context.SpringBootTest;

/** The whole application starts with the approved-document gate on, on the guides the migrations ship, and binds Q01's tools. */
@SpringBootTest(properties = {
        "ZOOP_AUTH_CSRF_ACTIVE_KEY_ID=test",
        "ZOOP_AUTH_CSRF_KEYS=test=AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA",
        "zoop.chat.approved-docs.enabled=true"
})
@EnabledIfEnvironmentVariable(named = "DB_URL", matches = "jdbc:postgresql:.*")
@Tag("auth-postgres")
class ChatApprovedDocsEnabledPostgresTest {
    @Autowired ChatToolRegistry registry;
    @Autowired ChatZoopDocs docs;

    @Test
    void theGateOpensBothReadsOnTheShippedGuides() {
        assertTrue(registry.bind(ChatCapability.HELP_SEARCH.id()).isPresent());
        assertTrue(registry.bind(ChatCapability.SCREEN_SPEC_READ.id()).isPresent());
        assertEquals("2026-11-02.1", docs.inEffect(ChatZoopDocs.HELP_GUIDE, null).orElseThrow().version());
        assertEquals("2026-11-02.1", docs.inEffect(ChatZoopDocs.SCREEN_GUIDE, null).orElseThrow().version());
    }
}
