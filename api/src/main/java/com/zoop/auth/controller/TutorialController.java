package com.zoop.auth.controller;

import java.util.Set;

import tools.jackson.databind.JsonNode;
import com.zoop.auth.config.MemberAuthorizationInterceptor;
import com.zoop.auth.dto.SessionResponse;
import com.zoop.auth.service.MemberSessionService;
import com.zoop.auth.service.MemberSessionService.MemberPrincipal;
import com.zoop.auth.service.MemberSettingsService;
import com.zoop.auth.service.SessionCookie;
import com.zoop.common.exception.CustomException;
import com.zoop.common.exception.ErrorCode;
import com.zoop.common.request.RequestIdFilter;
import io.swagger.v3.oas.annotations.Operation;
import jakarta.servlet.http.HttpServletRequest;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.CookieValue;
import org.springframework.web.bind.annotation.PutMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

@RestController
@RequestMapping("/api/v1/auth/tutorial")
public class TutorialController {
    private static final Set<String> FIELDS = Set.of("completed");
    private final MemberSettingsService settings;
    private final MemberSessionService sessions;

    public TutorialController(MemberSettingsService settings, MemberSessionService sessions) {
        this.settings = settings;
        this.sessions = sessions;
    }

    @PutMapping
    @Operation(summary = "튜토리얼 진행 결과 저장")
    public ResponseEntity<SessionResponse> update(
            @RequestBody JsonNode body,
            @CookieValue(name = SessionCookie.NAME) String token,
            HttpServletRequest request) {
        if (body == null || !body.isObject() || !FIELDS.equals(Set.copyOf(body.propertyNames()))
                || !body.get("completed").isBoolean()) {
            throw new CustomException(ErrorCode.INVALID_REQUEST);
        }
        String requestId = RequestIdFilter.currentId(request);
        settings.setTutorialCompleted(principal(request), body.get("completed").booleanValue(), requestId);
        return ResponseEntity.ok(sessions.lookup(token, requestId).response());
    }

    private static MemberPrincipal principal(HttpServletRequest request) {
        return (MemberPrincipal) request.getAttribute(MemberAuthorizationInterceptor.PRINCIPAL_ATTRIBUTE);
    }
}
