package com.zoop.auth.controller;

import com.zoop.auth.config.MemberAuthorizationInterceptor;
import com.zoop.auth.service.MemberSessionService;
import com.zoop.auth.service.SessionCookie;
import com.zoop.common.exception.CustomException;
import com.zoop.common.exception.ErrorCode;
import jakarta.servlet.http.Cookie;
import org.junit.jupiter.api.Test;
import org.springframework.mock.web.MockHttpServletRequest;
import org.springframework.mock.web.MockHttpServletResponse;

import static org.junit.jupiter.api.Assertions.*;
import static org.mockito.Mockito.*;

class MemberAuthorizationInterceptorTest {
    @Test
    void attachesAuthenticatedPrincipalForMemberResources() {
        var sessions = mock(MemberSessionService.class);
        var principal = new MemberSessionService.MemberPrincipal("member-1", "session-1");
        when(sessions.requireMember("m".repeat(43))).thenReturn(principal);
        var interceptor = new MemberAuthorizationInterceptor(sessions);
        var request = new MockHttpServletRequest("GET", "/api/v1/me/settings");
        request.setCookies(new Cookie(SessionCookie.NAME, "m".repeat(43)));

        assertTrue(interceptor.preHandle(request, new MockHttpServletResponse(), new Object()));
        assertSame(principal, request.getAttribute(MemberAuthorizationInterceptor.PRINCIPAL_ATTRIBUTE));
    }

    @Test
    void rejectsDuplicateSessionCookiesAtTheBoundary() {
        var sessions = mock(MemberSessionService.class);
        var interceptor = new MemberAuthorizationInterceptor(sessions);
        var request = new MockHttpServletRequest("GET", "/api/v1/me/settings");
        request.setCookies(new Cookie(SessionCookie.NAME, "a"), new Cookie(SessionCookie.NAME, "b"));
        var error = assertThrows(CustomException.class,
                () -> interceptor.preHandle(request, new MockHttpServletResponse(), new Object()));
        assertEquals(ErrorCode.ACCESS_DENIED, error.getErrorCode());
        verifyNoInteractions(sessions);
    }

    @Test
    void propagatesMemberRequiredForGuestSessions() {
        var sessions = mock(MemberSessionService.class);
        when(sessions.requireMember("g".repeat(43)))
                .thenThrow(new CustomException(ErrorCode.MEMBER_REQUIRED));
        var interceptor = new MemberAuthorizationInterceptor(sessions);
        var request = new MockHttpServletRequest("GET", "/api/v1/chat/sessions/current");
        request.setCookies(new Cookie(SessionCookie.NAME, "g".repeat(43)));

        var error = assertThrows(CustomException.class,
                () -> interceptor.preHandle(request, new MockHttpServletResponse(), new Object()));
        assertEquals(ErrorCode.MEMBER_REQUIRED, error.getErrorCode());
    }
}
