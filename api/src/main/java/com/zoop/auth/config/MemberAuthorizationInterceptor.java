package com.zoop.auth.config;

import com.zoop.auth.service.MemberSessionService;
import com.zoop.auth.service.SessionCookie;
import com.zoop.common.exception.CustomException;
import com.zoop.common.exception.ErrorCode;
import jakarta.servlet.http.Cookie;
import jakarta.servlet.http.HttpServletRequest;
import jakarta.servlet.http.HttpServletResponse;
import org.springframework.stereotype.Component;
import org.springframework.web.servlet.HandlerInterceptor;

/** Enforces member identity at the HTTP boundary for personal and question endpoints. */
@Component
public class MemberAuthorizationInterceptor implements HandlerInterceptor {
    public static final String PRINCIPAL_ATTRIBUTE = MemberAuthorizationInterceptor.class.getName() + ".principal";
    private final MemberSessionService sessions;

    public MemberAuthorizationInterceptor(MemberSessionService sessions) {
        this.sessions = sessions;
    }

    @Override
    public boolean preHandle(HttpServletRequest request, HttpServletResponse response, Object handler) {
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
        request.setAttribute(PRINCIPAL_ATTRIBUTE, sessions.requireMember(token));
        return true;
    }
}
