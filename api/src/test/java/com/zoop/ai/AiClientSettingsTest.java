package com.zoop.ai;

import java.time.Duration;
import java.util.Set;

import org.junit.jupiter.api.Test;

import static org.junit.jupiter.api.Assertions.assertDoesNotThrow;
import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertThrows;

class AiClientSettingsTest {
    private static final String TOKEN = "settings-token-0123456789abcdefghijklmnopqrstuv";
    private static final Duration CONNECT = Duration.ofSeconds(3);
    private static final Duration REQUEST = Duration.ofSeconds(30);

    private static AiClientSettings of(String url) {
        return AiClientSettings.of(url, TOKEN, CONNECT, REQUEST, 1 << 20);
    }

    @Test
    void plainHttpReachesOnlyTheExactListedHosts() {
        Set<String> hosts = Set.of("ai");
        assertEquals("http://ai:8000", AiClientSettings.of("http://ai:8000", TOKEN, CONNECT, REQUEST, 1 << 20, hosts)
                .baseUri().toString());
        assertDoesNotThrow(() -> AiClientSettings.of("http://AI:8000/ai", TOKEN, CONNECT, REQUEST, 1 << 20, hosts));
        assertDoesNotThrow(() -> AiClientSettings.of("https://ai.internal.example", TOKEN, CONNECT, REQUEST, 1 << 20, hosts));
        assertDoesNotThrow(() -> AiClientSettings.of("http://localhost:8797", TOKEN, CONNECT, REQUEST, 1 << 20, hosts));
        for (String url : new String[] {"http://ai.evil.example:8000", "http://evil-ai:8000", "http://10.0.0.5:8000",
                "http://user@ai:8000", "http://ai:8000?x=1"}) {
            AiClientConfigurationException error = assertThrows(AiClientConfigurationException.class,
                    () -> AiClientSettings.of(url, TOKEN, CONNECT, REQUEST, 1 << 20, hosts), url);
            assertEquals("base-url", error.setting());
        }
        assertThrows(AiClientConfigurationException.class, () -> of("http://ai:8000"), "the default list is empty");
        assertThrows(AiClientConfigurationException.class,
                () -> AiClientSettings.of("http://ai:8000", TOKEN, CONNECT, REQUEST, 1 << 20, null));
    }

    @Test
    void acceptsHttpsAnywhereAndLoopbackHttpOnly() {
        assertDoesNotThrow(() -> of("https://ai.internal.example"));
        assertDoesNotThrow(() -> of("https://ai.internal.example:8443/ai"));
        assertDoesNotThrow(() -> of("http://localhost:8797"));
        assertDoesNotThrow(() -> of("http://127.0.0.1:8797/"));
        assertDoesNotThrow(() -> of("http://[::1]:8797"));
        assertDoesNotThrow(() -> of("http://LOCALHOST:8797"), "host names compare case-insensitively");
        for (String url : new String[] {"http://ai.internal.example", "http://10.0.0.5:8797", "http://localhost.evil.example",
                "http://127.0.0.1.evil.example", "ftp://127.0.0.1", "file:///etc/passwd", "127.0.0.1:8797", "//127.0.0.1",
                "https://user:pw@ai.internal.example", "https://ai.internal.example?x=1", "https://ai.internal.example#f",
                "https://ai.internal.example/a/../b", "https://ai.internal.example/%2e%2e/b", "https://ai.internal.example/a b",
                "https://ai.internal.example:0", "", "   ", "https://"}) {
            AiClientConfigurationException error = assertThrows(AiClientConfigurationException.class, () -> of(url), url);
            assertEquals("base-url", error.setting());
            assertFalse(url.length() > 3 && error.getMessage().contains(url), "message must not echo the value: " + url);
        }
        assertThrows(AiClientConfigurationException.class, () -> of(null));
    }

    @Test
    void tokenMustBeAServiceBearerTokenAndIsNeverPrinted() {
        for (String token : new String[] {null, "", "short", "a".repeat(31), "a".repeat(513), "contains space " + "a".repeat(30),
                "ctrl\n" + "a".repeat(40), "한".repeat(40)}) {
            AiClientConfigurationException error = assertThrows(AiClientConfigurationException.class,
                    () -> AiClientSettings.of("https://ai.example", token, CONNECT, REQUEST, 1 << 20));
            assertEquals("token", error.setting());
            if (token != null && token.length() > 8) {
                assertFalse(error.getMessage().contains(token));
            }
        }
        AiClientSettings settings = of("https://ai.example");
        assertFalse(settings.toString().contains(TOKEN));
        assertFalse(settings.toString().contains("token=" + TOKEN));
    }

    @Test
    void timeoutsAndResponseLimitAreBounded() {
        assertThrows(AiClientConfigurationException.class,
                () -> AiClientSettings.of("https://ai.example", TOKEN, Duration.ofMillis(99), REQUEST, 1 << 20));
        assertThrows(AiClientConfigurationException.class,
                () -> AiClientSettings.of("https://ai.example", TOKEN, Duration.ofSeconds(31), REQUEST, 1 << 20));
        assertThrows(AiClientConfigurationException.class,
                () -> AiClientSettings.of("https://ai.example", TOKEN, CONNECT, Duration.ofMillis(99), 1 << 20));
        assertThrows(AiClientConfigurationException.class,
                () -> AiClientSettings.of("https://ai.example", TOKEN, CONNECT, Duration.ofSeconds(121), 1 << 20));
        assertThrows(AiClientConfigurationException.class,
                () -> AiClientSettings.of("https://ai.example", TOKEN, CONNECT, null, 1 << 20));
        assertThrows(AiClientConfigurationException.class,
                () -> AiClientSettings.of("https://ai.example", TOKEN, CONNECT, REQUEST, 1024));
        assertThrows(AiClientConfigurationException.class,
                () -> AiClientSettings.of("https://ai.example", TOKEN, CONNECT, REQUEST, 64 * 1024 * 1024));
        assertDoesNotThrow(() -> AiClientSettings.of("https://ai.example", TOKEN, Duration.ofMillis(100), Duration.ofSeconds(120), 65_536));
    }
}
