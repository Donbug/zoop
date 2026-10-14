package com.zoop.auth.service;

import com.zoop.common.exception.CustomException;
import com.zoop.common.exception.ErrorCode;
import org.junit.jupiter.api.Test;
import org.springframework.mock.web.MockHttpServletRequest;

import static org.junit.jupiter.api.Assertions.*;
import static org.mockito.Mockito.*;

class AuthRequestPolicyTest {
    @Test
    void originRequiresExactConfiguredHttpsValue() {
        var policy = new AuthOriginPolicy("https://zoop.example,https://zoop.example:8443");
        var request = new MockHttpServletRequest();
        assertDenied(policy, request);
        request.addHeader("Referer", "https://zoop.example/signup");
        assertDenied(policy, request);
        request.addHeader("Origin", "null");
        assertDenied(policy, request);
        request.removeHeader("Origin");
        request.addHeader("Origin", "https://zoop.example.evil");
        assertDenied(policy, request);
        request.removeHeader("Origin");
        request.addHeader("Origin", "http://zoop.example");
        assertDenied(policy, request);
        request.removeHeader("Origin");
        request.addHeader("Origin", "https://zoop.example:8443");
        policy.verify(request);
        assertDenied(new AuthOriginPolicy(""), request);
        assertThrows(IllegalArgumentException.class, () -> new AuthOriginPolicy("https://*.example"));
        assertThrows(IllegalArgumentException.class, () -> new AuthOriginPolicy("http://zoop.example"));
    }

    @Test
    void forwardedIpIsUsedOnlyWhenEveryCloserHopIsTrusted() {
        var resolver = new AuthClientIpResolver("192.0.2.10,192.0.2.11");
        var request = new MockHttpServletRequest();
        request.setRemoteAddr("198.51.100.9");
        request.addHeader("X-Forwarded-For", "203.0.113.7");
        assertEquals("198.51.100.9", resolver.resolve(request));

        request.setRemoteAddr("192.0.2.10");
        request.removeHeader("X-Forwarded-For");
        request.addHeader("X-Forwarded-For", "203.0.113.1, 198.51.100.2, 192.0.2.11");
        assertEquals("198.51.100.2", resolver.resolve(request));
        request.addHeader("X-Forwarded-For", "203.0.113.99");
        assertEquals(ErrorCode.ACCESS_DENIED,
                assertThrows(CustomException.class, () -> resolver.resolve(request)).getErrorCode());
        assertThrows(IllegalArgumentException.class,
                () -> new AuthClientIpResolver("proxy.example"));
    }

    @Test
    void gateRejectsOriginBeforeCountingAndCountsMalformedEmailByIp() {
        var rates = mock(AuthRateLimiter.class);
        var gate = new AuthAttemptGate(new AuthOriginPolicy("https://zoop.example"),
                new AuthClientIpResolver(""), rates);
        var request = new MockHttpServletRequest();
        request.setRemoteAddr("192.0.2.8");
        assertEquals(ErrorCode.ACCESS_DENIED,
                assertThrows(CustomException.class, () -> gate.signup(request, "bad"))
                        .getErrorCode());
        verifyNoInteractions(rates);

        request.addHeader("Origin", "https://zoop.example");
        assertEquals(ErrorCode.INVALID_REQUEST,
                assertThrows(CustomException.class, () -> gate.signup(request, "bad"))
                        .getErrorCode());
        verify(rates).recordSignupIpAttempt("192.0.2.8");
        assertEquals("user@example.com", gate.login(request, " User@Example.com ").key());
        verify(rates).recordLoginAttempt("192.0.2.8", "user@example.com");
    }

    private static void assertDenied(AuthOriginPolicy policy, MockHttpServletRequest request) {
        var error = assertThrows(CustomException.class, () -> policy.verify(request));
        assertEquals(ErrorCode.ACCESS_DENIED, error.getErrorCode());
    }
}
