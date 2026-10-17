package com.zoop.admin.auth.config;

import com.zoop.admin.auth.service.AdminSessionService;
import com.zoop.admin.auth.service.AdminSessionCookie;
import com.zoop.auth.service.AuthOriginPolicy;
import com.zoop.common.exception.CustomException;
import com.zoop.common.exception.ErrorCode;
import jakarta.servlet.http.HttpServletRequest;
import jakarta.servlet.http.HttpServletResponse;
import org.springframework.stereotype.Component;
import org.springframework.web.servlet.HandlerInterceptor;

/** Checks Origin and the session-bound admin CSRF token on authenticated admin writes. */
@Component
public class AdminCsrfInterceptor implements HandlerInterceptor {
    private final AuthOriginPolicy origins;
    private final AdminSessionService sessions;

    public AdminCsrfInterceptor(AuthOriginPolicy origins, AdminSessionService sessions) {
        this.origins = origins;
        this.sessions = sessions;
    }

    @Override
    public boolean preHandle(HttpServletRequest request, HttpServletResponse response, Object handler) {
        if ("GET".equals(request.getMethod()) || "HEAD".equals(request.getMethod())
                || "OPTIONS".equals(request.getMethod())) return true;
        String token = AdminSessionCookie.token(request);
        if (token == null) return true;
        String path = request.getRequestURI().substring(request.getContextPath().length());
        if ("/api/v1/admin/auth/logout".equals(path) && !sessions.isActiveSession(token)) return true;
        origins.verify(request);
        var headers = request.getHeaders("X-CSRF-Token");
        if (!headers.hasMoreElements()) throw new CustomException(ErrorCode.ACCESS_DENIED);
        String csrf = headers.nextElement();
        if (headers.hasMoreElements()) throw new CustomException(ErrorCode.ACCESS_DENIED);
        sessions.verifyCsrf(token, csrf);
        return true;
    }
}
