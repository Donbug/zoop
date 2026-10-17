package com.zoop.auth.service;

import java.nio.charset.StandardCharsets;
import java.security.InvalidKeyException;
import java.security.NoSuchAlgorithmException;
import java.util.Base64;
import java.util.Collections;
import java.util.HashMap;
import java.util.Map;
import java.util.Optional;

import javax.crypto.Mac;
import javax.crypto.spec.SecretKeySpec;

/** ERD v6 session-bound CSRF derivation. Key material is never persisted. */
public final class CsrfKeyRing {
    private final String activeKeyId;
    private final Map<String, byte[]> keys;

    public CsrfKeyRing(String activeKeyId, String encodedKeys) {
        if (activeKeyId == null || !activeKeyId.matches("[A-Za-z0-9_-]{1,64}")) {
            throw new IllegalArgumentException("Invalid CSRF key configuration");
        }
        Map<String, byte[]> parsed = new HashMap<>();
        if (encodedKeys != null && !encodedKeys.isBlank()) {
            for (String entry : encodedKeys.split(",", -1)) {
                String[] parts = entry.split("=", 2);
                if (parts.length != 2 || !parts[0].matches("[A-Za-z0-9_-]{1,64}")) {
                    throw new IllegalArgumentException("Invalid CSRF key configuration");
                }
                try {
                    byte[] key = Base64.getUrlDecoder().decode(parts[1]);
                    if (key.length < 32 || parsed.putIfAbsent(parts[0], key) != null) {
                        throw new IllegalArgumentException("Invalid CSRF key configuration");
                    }
                } catch (IllegalArgumentException exception) {
                    throw new IllegalArgumentException("Invalid CSRF key configuration");
                }
            }
        }
        if (!parsed.containsKey(activeKeyId)) {
            throw new IllegalArgumentException("Invalid CSRF key configuration");
        }
        this.activeKeyId = activeKeyId;
        this.keys = Collections.unmodifiableMap(parsed);
    }

    public String activeKeyId() {
        return activeKeyId;
    }

    public Optional<String> derive(String keyId, String sessionKind, String sessionId, long version) {
        byte[] key = keys.get(keyId);
        if (key == null) {
            return Optional.empty();
        }
        if (!sessionKind.matches("member|guest|admin|oauth_pending")
                || !sessionId.matches("[A-Za-z0-9_-]{1,128}") || version < 1) {
            throw new IllegalArgumentException("Invalid CSRF session identity");
        }
        String message = "[\"zoop-csrf-v1\",\"" + sessionKind + "\",\"" + sessionId + "\"," + version + "]";
        try {
            Mac mac = Mac.getInstance("HmacSHA256");
            mac.init(new SecretKeySpec(key, "HmacSHA256"));
            return Optional.of(Base64.getUrlEncoder().withoutPadding()
                    .encodeToString(mac.doFinal(message.getBytes(StandardCharsets.UTF_8))));
        } catch (NoSuchAlgorithmException | InvalidKeyException exception) {
            throw new IllegalStateException("CSRF derivation unavailable", exception);
        }
    }
}
