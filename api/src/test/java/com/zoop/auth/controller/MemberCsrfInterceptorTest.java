package com.zoop.auth.controller;

import com.zoop.auth.config.MemberCsrfInterceptor;
import com.zoop.auth.service.AuthOriginPolicy;
import com.zoop.auth.service.MemberSessionService;
import com.zoop.common.exception.CustomException;
import com.zoop.common.exception.ErrorCode;
import jakarta.servlet.http.Cookie;
import org.junit.jupiter.api.Test;
import org.springframework.mock.web.MockHttpServletRequest;
import org.springframework.mock.web.MockHttpServletResponse;

import static org.junit.jupiter.api.Assertions.*;
import static org.mockito.Mockito.*;

class MemberCsrfInterceptorTest {
    private final MemberSessionService sessions = mock(MemberSessionService.class);
    private final MemberCsrfInterceptor interceptor = new MemberCsrfInterceptor(
            new AuthOriginPolicy("https://zoop.example"), sessions);

    @Test
    void memberCookieWriteRequiresAllowedOriginAndOneCsrfHeader() {
        var request = request("POST", true);
        request.addHeader("Origin", "https://zoop.example");
        request.addHeader("X-CSRF-Token", "csrf");
        assertTrue(interceptor.preHandle(request, new MockHttpServletResponse(), new Object()));
        verify(sessions).verifyCsrf("token", "csrf");

        var badOrigin = request("PATCH", true);
        badOrigin.addHeader("Origin", "https://attacker.example");
        badOrigin.addHeader("X-CSRF-Token", "csrf");
        assertDenied(badOrigin);

        var noCsrf = request("DELETE", true);
        noCsrf.addHeader("Origin", "https://zoop.example");
        assertDenied(noCsrf);
        noCsrf.addHeader("X-CSRF-Token", "first");
        noCsrf.addHeader("X-CSRF-Token", "second");
        assertDenied(noCsrf);
    }

    @Test
    void readsAndCookieFreeRequestsDoNotInvokeCsrfVerification() {
        var read = request("GET", true);
        assertTrue(interceptor.preHandle(read, new MockHttpServletResponse(), new Object()));
        var noCookie = request("POST", false);
        assertTrue(interceptor.preHandle(noCookie, new MockHttpServletResponse(), new Object()));
        verifyNoInteractions(sessions);
    }

    @Test
    void duplicateMemberCookiesAreDenied() {
        var request = request("POST", true);
        request.setCookies(new Cookie("zoop_session", "one"), new Cookie("zoop_session", "two"));
        assertDenied(request);
    }

    @Test
    void logoutSkipsOriginAndCsrfOnlyWhenSessionIsNotActive() {
        var noCookie = new MockHttpServletRequest("POST", "/api/v1/auth/logout");
        assertTrue(interceptor.preHandle(noCookie, new MockHttpServletResponse(), new Object()));

        var expired = new MockHttpServletRequest("POST", "/api/v1/auth/logout");
        expired.setCookies(new Cookie("zoop_session", "expired"));
        when(sessions.isActiveSession("expired")).thenReturn(false);
        assertTrue(interceptor.preHandle(expired, new MockHttpServletResponse(), new Object()));
        verify(sessions, never()).verifyCsrf(anyString(), anyString());
    }

    @Test
    void activeLogoutSessionStillRequiresAllowedOriginAndCsrf() {
        var request = new MockHttpServletRequest("POST", "/api/v1/auth/logout");
        request.setCookies(new Cookie("zoop_session", "token"));
        when(sessions.isActiveSession("token")).thenReturn(true);
        request.addHeader("Origin", "https://zoop.example");
        request.addHeader("X-CSRF-Token", "csrf");

        assertTrue(interceptor.preHandle(request, new MockHttpServletResponse(), new Object()));
        verify(sessions).verifyCsrf("token", "csrf");

        var missingCsrf = new MockHttpServletRequest("POST", "/api/v1/auth/logout");
        missingCsrf.setCookies(new Cookie("zoop_session", "token"));
        missingCsrf.addHeader("Origin", "https://zoop.example");
        assertDenied(missingCsrf);
    }

    private MockHttpServletRequest request(String method, boolean cookie) {
        var request = new MockHttpServletRequest(method, "/api/v1/member/example");
        if (cookie) {
            request.setCookies(new Cookie("zoop_session", "token"));
        }
        return request;
    }

    private void assertDenied(MockHttpServletRequest request) {
        var error = assertThrows(CustomException.class,
                () -> interceptor.preHandle(request, new MockHttpServletResponse(), new Object()));
        assertEquals(ErrorCode.ACCESS_DENIED, error.getErrorCode());
    }
}
