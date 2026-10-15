package com.zoop.auth.service;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;

import com.zoop.common.exception.CustomException;
import org.junit.jupiter.api.Test;

class PasswordHashServiceTest {
    private final PasswordHashService hashes = new PasswordHashService(new CredentialPolicy());

    @Test
    void eachHashHasItsOwnSaltAndOnlyTheOriginalPasswordMatches() {
        String password = "  아주 긴 비밀번호 123456  ";
        String first = hashes.hashNewPassword(password);
        String second = hashes.hashNewPassword(password);

        assertThat(first).startsWith("{argon2id-v1}$argon2id$").doesNotContain(password);
        assertThat(first).isNotEqualTo(second);
        assertThat(hashes.matches(password, first)).isTrue();
        assertThat(hashes.matches(password.trim(), first)).isFalse();
        assertThat(hashes.matches("different-password", first)).isFalse();
    }

    @Test
    void unknownOrMissingStoredHashDoesNotAuthenticate() {
        assertThat(hashes.matches("password", null)).isFalse();
        assertThat(hashes.matches("password", "{unknown}hash")).isFalse();
        assertThat(hashes.matches(null, hashes.hashNewPassword("valid password 123"))).isFalse();
        assertThatThrownBy(() -> hashes.hashNewPassword("short")).isInstanceOf(CustomException.class);
    }
}
