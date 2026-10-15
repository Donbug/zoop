package com.zoop.auth.config;

import com.zoop.auth.service.CsrfKeyRing;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;

@Configuration
public class CsrfConfiguration {
    @Bean
    CsrfKeyRing csrfKeyRing(
            @Value("${ZOOP_AUTH_CSRF_ACTIVE_KEY_ID:}") String activeKeyId,
            @Value("${ZOOP_AUTH_CSRF_KEYS:}") String encodedKeys) {
        return new CsrfKeyRing(activeKeyId, encodedKeys);
    }
}
