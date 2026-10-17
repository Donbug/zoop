package com.zoop.auth.service;

import java.io.BufferedReader;
import java.io.IOException;
import java.io.InputStreamReader;
import java.nio.charset.StandardCharsets;
import java.util.Locale;
import java.util.Set;
import java.util.stream.Collectors;

import com.zoop.common.exception.CustomException;
import com.zoop.common.exception.ErrorCode;
import org.springframework.stereotype.Component;

@Component
public final class CredentialPolicy {
    private static final int PASSWORD_MIN_CODE_POINTS = 8;
    private static final int PASSWORD_MAX_CODE_POINTS = 32;
    private static final int DISPLAY_NAME_MAX_CODE_POINTS = 40;

    private final Set<String> commonPasswords;

    public CredentialPolicy() {
        try (var input = CredentialPolicy.class.getResourceAsStream("/auth/common-passwords-v2.txt")) {
            if (input == null) {
                throw new IllegalStateException("Common password list is missing");
            }
            try (var reader = new BufferedReader(new InputStreamReader(input, StandardCharsets.UTF_8))) {
                commonPasswords = reader.lines().filter(line -> !line.isBlank() && !line.startsWith("#"))
                        .map(line -> line.toLowerCase(Locale.ROOT)).collect(Collectors.toUnmodifiableSet());
            }
        } catch (IOException exception) {
            throw new IllegalStateException("Common password list cannot be read", exception);
        }
    }

    public EmailAddress email(String input) {
        return EmailAddress.parse(input);
    }

    public String displayName(String input) {
        if (input == null) {
            return "회원";
        }
        String value = input.strip();
        if (value.isEmpty() || value.codePointCount(0, value.length()) > DISPLAY_NAME_MAX_CODE_POINTS
                || containsInvalidCodePoint(value)) {
            throw new CustomException(ErrorCode.INVALID_REQUEST);
        }
        return value;
    }

    public void newPassword(String password) {
        if (password == null || password.codePointCount(0, password.length()) < PASSWORD_MIN_CODE_POINTS
                || password.codePointCount(0, password.length()) > PASSWORD_MAX_CODE_POINTS
                || containsInvalidCodePoint(password) || commonPasswords.contains(password.toLowerCase(Locale.ROOT))) {
            throw new CustomException(ErrorCode.INVALID_REQUEST);
        }
    }

    private static boolean containsInvalidCodePoint(String value) {
        return value.codePoints().anyMatch(codePoint -> Character.isISOControl(codePoint)
                || codePoint >= Character.MIN_SURROGATE && codePoint <= Character.MAX_SURROGATE);
    }
}
