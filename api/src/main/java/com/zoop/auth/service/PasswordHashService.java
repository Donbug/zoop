package com.zoop.auth.service;

import java.util.Map;

import org.springframework.security.crypto.argon2.Argon2PasswordEncoder;
import org.springframework.security.crypto.password.DelegatingPasswordEncoder;
import org.springframework.security.crypto.password.PasswordEncoder;
import org.springframework.stereotype.Component;

@Component
public final class PasswordHashService {
    private static final String ENCODER_ID = "argon2id-v1";
    private final PasswordEncoder encoder = new DelegatingPasswordEncoder(ENCODER_ID,
            Map.of(ENCODER_ID, new Argon2PasswordEncoder(16, 32, 1, 19 * 1024, 2)));
    private final CredentialPolicy credentialPolicy;
    private final String dummyHash;

    public PasswordHashService(CredentialPolicy credentialPolicy) {
        this.credentialPolicy = credentialPolicy;
        this.dummyHash = encoder.encode("never-a-real-member-password");
    }

    public String hashNewPassword(String password) {
        credentialPolicy.newPassword(password);
        return encoder.encode(password);
    }

    public boolean matches(String password, String storedHash) {
        if (password == null || storedHash == null || !storedHash.startsWith("{" + ENCODER_ID + "}")) {
            return false;
        }
        try {
            return encoder.matches(password, storedHash);
        } catch (IllegalArgumentException exception) {
            return false;
        }
    }

    /** Spend the same hash-verification work when the account has no email password. */
    public boolean matchesOrDummy(String password, String storedHash) {
        boolean matched = matches(password, storedHash == null ? dummyHash : storedHash);
        return storedHash != null && matched;
    }
}
