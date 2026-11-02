package com.zoop.ai.config;

import java.util.Arrays;
import java.util.List;
import java.util.Set;

import com.zoop.ai.AiClientConfigurationException;
import org.junit.jupiter.api.Test;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertThrows;

class AiTransportPropertiesTest {
    @Test
    void absentOrBlankListsAllowNoPlainHost() {
        assertEquals(Set.of(), new AiTransportProperties(null).hosts());
        assertEquals(Set.of(), new AiTransportProperties(List.of()).hosts());
        assertEquals(Set.of(), new AiTransportProperties(Arrays.asList("", "  ", null)).hosts());
    }

    @Test
    void keepsExactLowerCaseHostNames() {
        var properties = new AiTransportProperties(List.of(" ai ", "ai-service.internal", "ai", "ai2.10"));
        assertEquals(Set.of("ai", "ai-service.internal", "ai2.10"), properties.hosts());
    }

    @Test
    void refusesAnythingButAHostNameWithoutEchoingIt() {
        for (String bad : new String[] {"*", "*.internal", "AI", "ai:8000", "http://ai", "ai/", "ai.", ".ai", "a..b", "-ai",
                "ai-", "a_i", "10.0.0.5", "8000", "a".repeat(64), ("a".repeat(63) + ".").repeat(4) + "a"}) {
            AiClientConfigurationException error = assertThrows(AiClientConfigurationException.class,
                    () -> new AiTransportProperties(List.of("ai", bad)).hosts(), bad);
            assertEquals("plaintext-http-hosts", error.setting());
            // The fixed message carries the setting name only, never the refused value.
            assertEquals("zoop.ai.plaintext-http-hosts must list lower-case host names only", error.getMessage());
        }
    }
}
