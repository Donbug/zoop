package com.zoop.auth.service;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;

import com.zoop.common.exception.CustomException;
import com.zoop.common.exception.ErrorCode;
import org.junit.jupiter.api.Test;

class CredentialPolicyTest {
    private final CredentialPolicy policy = new CredentialPolicy();

    @Test
    void signupAndLoginUseTheSameEmailKeyWithoutProviderAliasRules() {
        EmailAddress signup = policy.email("  First.Name+news@Example.COM  ");
        EmailAddress login = policy.email("first.name+news@example.com");

        assertThat(signup.value()).isEqualTo("First.Name+news@Example.COM");
        assertThat(signup.key()).isEqualTo(login.key());
        assertThat(policy.email("firstname@example.com").key()).isNotEqualTo(signup.key());
    }

    @Test
    void rejectsMalformedOrUnsupportedEmailBeforeAnyLookup() {
        for (String input : new String[] {"", "no-at-sign", "a@@example.com", ".a@example.com",
                "a..b@example.com", "a@-example.com", "a@example", "a@ex ample.com", "한글@example.com"}) {
            assertInvalid(() -> policy.email(input));
        }
        assertInvalid(() -> policy.email(null));
    }

    @Test
    void appliesDisplayNamePolicyWithoutDerivingIdentityFromEmail() {
        assertThat(policy.displayName(null)).isEqualTo("회원");
        assertThat(policy.displayName("  한글 이름  ")).isEqualTo("한글 이름");
        assertInvalid(() -> policy.displayName("   "));
        assertInvalid(() -> policy.displayName("x".repeat(41)));
        assertInvalid(() -> policy.displayName("a\nname"));
        assertInvalid(() -> policy.displayName("a\uD800"));
    }

    @Test
    void acceptsLongUnicodePasswordsWithoutTrimmingAndRejectsKnownCommonValues() {
        policy.newPassword("   Correct Horse Battery Staple   ");
        policy.newPassword("가".repeat(15));
        assertInvalid(() -> policy.newPassword("short"));
        assertInvalid(() -> policy.newPassword("x".repeat(129)));
        assertInvalid(() -> policy.newPassword("password1234567"));
        assertInvalid(() -> policy.newPassword("valid password\nmore"));
        assertInvalid(() -> policy.newPassword("valid password \uD800"));
    }

    private static void assertInvalid(Runnable action) {
        assertThatThrownBy(action::run).isInstanceOf(CustomException.class)
                .extracting(exception -> ((CustomException) exception).getErrorCode())
                .isEqualTo(ErrorCode.INVALID_REQUEST);
    }
}
