package com.zoop.admin.auth.config;

import com.zoop.admin.auth.service.AdminPrincipal;
import com.zoop.admin.auth.service.AdminSessionCookie;
import com.zoop.admin.auth.service.AdminSessionService;
import com.zoop.common.exception.CustomException;
import com.zoop.common.exception.ErrorCode;
import jakarta.servlet.http.Cookie;
import jakarta.servlet.http.HttpServletRequest;
import jakarta.servlet.http.HttpServletResponse;
import org.springframework.stereotype.Component;
import org.springframework.web.cors.CorsUtils;
import org.springframework.web.servlet.HandlerInterceptor;

/** Enforces current administrator identity and the configured admin-all permission at the HTTP boundary. */
@Component
public class AdminAuthorizationInterceptor implements HandlerInterceptor {
    public static final String PRINCIPAL_ATTRIBUTE = AdminAuthorizationInterceptor.class.getName() + ".principal";
    private final AdminSessionService sessions;

    public AdminAuthorizationInterceptor(AdminSessionService sessions) {
        this.sessions = sessions;
    }

    @Override
    public boolean preHandle(HttpServletRequest request, HttpServletResponse response, Object handler) {
        if (CorsUtils.isPreFlightRequest(request)) {
            return true;
        }
        String token = AdminSessionCookie.token(request);
        AdminPrincipal principal = sessions.requireAdmin(token);
        if (!AdminPermissions.can(principal.role(), requiredPermission(request))) {
            throw new CustomException(ErrorCode.ACCESS_DENIED);
        }
        request.setAttribute(PRINCIPAL_ATTRIBUTE, principal);
        return true;
    }

    private static String requiredPermission(HttpServletRequest request) {
        return "admin:all";
    }
}
