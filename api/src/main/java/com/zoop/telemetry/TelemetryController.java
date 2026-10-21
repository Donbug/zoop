package com.zoop.telemetry;

import com.zoop.auth.config.MemberAuthorizationInterceptor;
import com.zoop.auth.service.MemberSessionService;
import com.zoop.common.request.RequestIdFilter;
import io.swagger.v3.oas.annotations.Operation;
import jakarta.servlet.http.HttpServletRequest;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestHeader;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;
import org.springframework.http.HttpStatus;
import org.springframework.web.bind.annotation.ResponseStatus;
import tools.jackson.databind.JsonNode;

@RestController
@RequestMapping("/api/v1/telemetry")
public class TelemetryController {
    private final MemberSessionService sessions;
    private final TelemetryService telemetry;

    public TelemetryController(MemberSessionService sessions, TelemetryService telemetry) {
        this.sessions = sessions;
        this.telemetry = telemetry;
    }

    @PostMapping
    @ResponseStatus(HttpStatus.ACCEPTED)
    @Operation(operationId = "recordInteractionEvents", summary = "허용된 사용 이벤트 접수")
    public TelemetryService.Accepted record(@RequestBody JsonNode body,
            @RequestHeader("Idempotency-Key") String idempotencyKey, HttpServletRequest request) {
        String principal = sessions.analyticsPrincipal(MemberAuthorizationInterceptor.sessionToken(request));
        return telemetry.record(principal, idempotencyKey, body, RequestIdFilter.currentId(request));
    }
}
