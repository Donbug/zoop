package com.zoop.admin.auth.config;

import com.zoop.admin.auth.service.AdminSessionService;
import com.zoop.admin.auth.service.AdminPrincipal;
import com.zoop.common.exception.CustomException;
import com.zoop.common.exception.ErrorCode;
import org.junit.jupiter.api.Test;
import org.springframework.mock.web.MockHttpServletRequest;
import org.springframework.mock.web.MockHttpServletResponse;

import static org.junit.jupiter.api.Assertions.assertTrue;
import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.verifyNoInteractions;
import static org.mockito.Mockito.when;

class AdminAuthorizationInterceptorTest {
    @Test
    void allowsCorsPreflightWithoutAdminAuthentication() {
        var sessions = mock(AdminSessionService.class);
        var interceptor = new AdminAuthorizationInterceptor(sessions);
        var request = new MockHttpServletRequest("OPTIONS", "/api/v1/admin/members");
        request.addHeader("Origin", "http://localhost:5173");
        request.addHeader("Access-Control-Request-Method", "GET");

        assertTrue(interceptor.preHandle(request, new MockHttpServletResponse(), new Object()));
        verifyNoInteractions(sessions);
    }

    @Test
    void auditLogRejectsAuthenticatedPrincipalWithoutAdminPermission() {
        var sessions = mock(AdminSessionService.class);
        var interceptor = new AdminAuthorizationInterceptor(sessions);
        var request = new MockHttpServletRequest("GET", "/api/v1/admin/audit-log");
        request.setCookies(new jakarta.servlet.http.Cookie("zoop_admin_session", "test-token"));
        when(sessions.requireAdmin(org.mockito.ArgumentMatchers.any()))
                .thenReturn(new AdminPrincipal("operator", "operator@example.com",
                        "Operator", "viewer", "session"));

        var failure = assertThrows(CustomException.class,
                () -> interceptor.preHandle(request, new MockHttpServletResponse(), new Object()));
        assertEquals(ErrorCode.ACCESS_DENIED, failure.getErrorCode());
    }
}
