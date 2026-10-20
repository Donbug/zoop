package com.zoop.auth.config;

import static org.junit.jupiter.api.Assertions.assertDoesNotThrow;
import static org.junit.jupiter.api.Assertions.assertThrows;

import java.time.Duration;

import org.junit.jupiter.api.Test;

class SocialAuthConfigurationValidatorTest {
    @Test
    void requiresFrontendOriginWhenSocialProviderIsConfigured() {
        var settings = new SocialAuthSettings(Duration.ofMinutes(10), 30, 10,
                "/login,/signup,/", false, "", "google-client", "google-secret",
                "https://api.example.com/callback", "", "", "");

        assertThrows(IllegalArgumentException.class, () -> new SocialAuthConfigurationValidator(settings));
    }

    @Test
    void doesNotRequireFrontendOriginWhenNoProviderIsConfigured() {
        var settings = new SocialAuthSettings(Duration.ofMinutes(10), 30, 10,
                "/login,/signup,/", false, "", "", "", "", "", "", "");

        assertDoesNotThrow(() -> new SocialAuthConfigurationValidator(settings));
    }
}
