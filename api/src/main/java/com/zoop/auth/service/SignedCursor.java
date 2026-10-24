package com.zoop.auth.service;

import java.security.MessageDigest;
import java.util.Base64;
import tools.jackson.databind.ObjectMapper;

/**
 * The opaque server cursor format shared by the admin lists: {@code base64url(json).base64url(mac)}, signed by the
 * {@link CsrfKeyRing} under a per-list purpose so one list's cursor never verifies as another's. Each list checks the fields
 * it binds (admin, filters, limit) after {@link #decode}.
 */
public final class SignedCursor {
    private static final int MAX_LENGTH = 4096;

    /** A cursor position names the key that signed it. */
    public interface Position {
        String keyId();
    }

    private SignedCursor() {
    }

    /**
     * The verified position, or null when there is no cursor.
     *
     * @throws IllegalArgumentException when the value is malformed, signed by an unknown key or not signed for {@code purpose}
     */
    public static <T extends Position> T decode(ObjectMapper mapper, CsrfKeyRing keys, String purpose, String value,
            Class<T> type) {
        if (value == null) return null;
        if (value.isBlank() || value.length() > MAX_LENGTH) throw new IllegalArgumentException("cursor length");
        String[] parts = value.split("[.]", -1);
        if (parts.length != 2) throw new IllegalArgumentException("cursor shape");
        byte[] payload = Base64.getUrlDecoder().decode(parts[0]);
        byte[] signature = Base64.getUrlDecoder().decode(parts[1]);
        T position = mapper.readValue(payload, type);
        if (position == null || position.keyId() == null || !position.keyId().matches("[A-Za-z0-9_-]{1,64}")) {
            throw new IllegalArgumentException("cursor key");
        }
        byte[] expected = keys.sign(position.keyId(), purpose, payload)
                .orElseThrow(() -> new IllegalArgumentException("cursor key unknown"));
        if (!MessageDigest.isEqual(expected, signature)) throw new IllegalArgumentException("cursor signature");
        return position;
    }

    public static String encode(ObjectMapper mapper, CsrfKeyRing keys, String purpose, Position position) {
        try {
            byte[] payload = mapper.writeValueAsBytes(position);
            byte[] signature = keys.sign(position.keyId(), purpose, payload).orElseThrow();
            return Base64.getUrlEncoder().withoutPadding().encodeToString(payload) + "."
                    + Base64.getUrlEncoder().withoutPadding().encodeToString(signature);
        } catch (Exception exception) {
            throw new IllegalStateException("Unable to encode " + purpose, exception);
        }
    }
}
