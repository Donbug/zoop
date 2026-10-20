package com.zoop.admin.auth.config;

import com.zoop.admin.auth.service.AdminSessionService;
import org.junit.jupiter.api.Test;
import org.springframework.mock.web.MockHttpServletRequest;
import org.springframework.mock.web.MockHttpServletResponse;

import static org.junit.jupiter.api.Assertions.assertTrue;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.verifyNoInteractions;

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
}
