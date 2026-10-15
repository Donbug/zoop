package com.zoop.auth.config;

import com.zoop.auth.service.AuthOriginPolicy;
import com.zoop.auth.service.MemberSessionService;
import com.zoop.auth.service.SessionCookie;
import com.zoop.common.exception.CustomException;
import com.zoop.common.exception.ErrorCode;
import jakarta.servlet.http.Cookie;
import jakarta.servlet.http.HttpServletRequest;
import jakarta.servlet.http.HttpServletResponse;
import org.springframework.stereotype.Component;
import org.springframework.web.servlet.HandlerInterceptor;

/** Protects member/guest-cookie writes; authorization of cookie-free requests belongs to each resource. */
@Component
public class MemberCsrfInterceptor implements HandlerInterceptor {
    private final AuthOriginPolicy origins;
    private final MemberSessionService sessions;

    public MemberCsrfInterceptor(AuthOriginPolicy origins, MemberSessionService sessions) {
        this.origins = origins;
        this.sessions = sessions;
    }

    @Override
    public boolean preHandle(HttpServletRequest request, HttpServletResponse response, Object handler) {
        if ("GET".equals(request.getMethod()) || "HEAD".equals(request.getMethod())
                || "OPTIONS".equals(request.getMethod())) {
            return true;
        }
        String token = null;
        if (request.getCookies() != null) {
            for (Cookie cookie : request.getCookies()) {
                if (SessionCookie.NAME.equals(cookie.getName())) {
                    if (token != null) {
                        throw new CustomException(ErrorCode.ACCESS_DENIED);
                    }
                    token = cookie.getValue();
                }
            }
        }
        if (token != null) {
            String path = request.getRequestURI().substring(request.getContextPath().length());
            if ("/api/v1/auth/logout".equals(path) && !sessions.isActiveSession(token)) {
                return true;
            }
            origins.verify(request);
            var headers = request.getHeaders("X-CSRF-Token");
            if (!headers.hasMoreElements()) {
                throw new CustomException(ErrorCode.ACCESS_DENIED);
            }
            String csrf = headers.nextElement();
            if (headers.hasMoreElements()) {
                throw new CustomException(ErrorCode.ACCESS_DENIED);
            }
            sessions.verifyCsrf(token, csrf);
        }
        return true;
    }
}
