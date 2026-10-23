package com.zoop.auth.config;

import org.springframework.context.annotation.Profile;
import org.springframework.stereotype.Component;

/** Validates web-facing social-auth configuration; headless operator commands do not need it. */
@Component
@Profile("!admin-provision & !catalog-import")
public class SocialAuthConfigurationValidator {
    public SocialAuthConfigurationValidator(SocialAuthSettings settings) {
        boolean providerConfigured = settings.providerConfigured(settings.provider("google"))
                || settings.providerConfigured(settings.provider("kakao"));
        if (providerConfigured && !settings.hasFrontendOrigin()) {
            throw new IllegalArgumentException("Social auth requires a valid frontend origin");
        }
    }
}
