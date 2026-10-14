package com.zoop.auth.service;

import java.util.Locale;

import com.zoop.common.exception.CustomException;
import com.zoop.common.exception.ErrorCode;

/** The same stored address and comparison key must be used by signup and login. */
public final class EmailAddress {
    private static final int MAX_LENGTH = 254;
    private static final int MAX_LOCAL_LENGTH = 64;

    private final String value;
    private final String key;

    private EmailAddress(String value) {
        this.value = value;
        this.key = value.toLowerCase(Locale.ROOT);
    }

    public static EmailAddress parse(String input) {
        if (input == null) {
            throw invalid();
        }
        String value = input.strip();
        if (value.isEmpty() || value.length() > MAX_LENGTH || !value.chars().allMatch(c -> c >= 33 && c <= 126)) {
            throw invalid();
        }
        int at = value.indexOf('@');
        if (at < 1 || at != value.lastIndexOf('@') || at > MAX_LOCAL_LENGTH || at == value.length() - 1) {
            throw invalid();
        }
        String local = value.substring(0, at);
        String domain = value.substring(at + 1);
        if (local.startsWith(".") || local.endsWith(".") || local.contains("..")
                || !local.chars().allMatch(EmailAddress::isLocalCharacter)) {
            throw invalid();
        }
        String[] labels = domain.split("\\.", -1);
        if (labels.length < 2) {
            throw invalid();
        }
        for (String label : labels) {
            if (label.isEmpty() || label.length() > 63 || label.startsWith("-") || label.endsWith("-")
                    || !label.chars().allMatch(c -> isAsciiLetterOrDigit(c) || c == '-')) {
                throw invalid();
            }
        }
        return new EmailAddress(value);
    }

    private static boolean isLocalCharacter(int c) {
        return isAsciiLetterOrDigit(c) || ".!#$%&'*+/=?^_`{|}~-".indexOf(c) >= 0;
    }

    private static boolean isAsciiLetterOrDigit(int c) {
        return c >= 'a' && c <= 'z' || c >= 'A' && c <= 'Z' || c >= '0' && c <= '9';
    }

    private static CustomException invalid() {
        return new CustomException(ErrorCode.INVALID_REQUEST);
    }

    public String value() {
        return value;
    }

    public String key() {
        return key;
    }
}
