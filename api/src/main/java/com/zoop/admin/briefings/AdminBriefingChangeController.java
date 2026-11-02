package com.zoop.admin.briefings;

import com.zoop.admin.auth.config.AdminAuthorizationInterceptor;
import com.zoop.admin.auth.service.AdminPrincipal;
import com.zoop.common.exception.CustomException;
import com.zoop.common.exception.ErrorCode;
import com.zoop.common.request.RequestIdFilter;
import io.swagger.v3.oas.annotations.Operation;
import jakarta.servlet.http.HttpServletRequest;
import jakarta.validation.Valid;
import jakarta.validation.constraints.NotBlank;
import jakarta.validation.constraints.Pattern;
import jakarta.validation.constraints.Size;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;
import tools.jackson.databind.node.ObjectNode;

/** A-ADM-04 / FS071: append-only publication changes, authenticated by admin session and CSRF. */
@RestController
@RequestMapping("/api/v1/admin/briefings")
public class AdminBriefingChangeController {
    private final AdminBriefingChangeService changes;

    public AdminBriefingChangeController(AdminBriefingChangeService changes) { this.changes = changes; }

    public record Correction(@Size(max = 300) String eventId,
            @NotBlank @Size(max = 2000) String correctedText, @NotBlank @Size(max = 500) String reason) { }
    public record Suspension(@NotBlank @Pattern(regexp = "suspend|resume") String action,
            @NotBlank @Size(max = 500) String reason) { }

    @PostMapping("/{roundId}/corrections")
    @Operation(operationId = "appendBriefingCorrection", summary = "발행 원문을 유지하는 정정 등록")
    public ResponseEntity<ObjectNode> correct(@PathVariable String roundId, @Valid @RequestBody Correction body,
            HttpServletRequest request) {
        return ResponseEntity.status(201).body(changes.correct(roundId, body, key(request), principal(request),
                RequestIdFilter.currentId(request)));
    }

    @PostMapping("/{roundId}/suspension")
    @Operation(operationId = "setBriefingSuspension", summary = "브리핑 제공 중단·재개")
    public ObjectNode suspend(@PathVariable String roundId, @Valid @RequestBody Suspension body,
            HttpServletRequest request) {
        return changes.suspend(roundId, body, key(request), principal(request), RequestIdFilter.currentId(request));
    }

    private static AdminPrincipal principal(HttpServletRequest request) {
        return (AdminPrincipal) request.getAttribute(AdminAuthorizationInterceptor.PRINCIPAL_ATTRIBUTE);
    }
    private static String key(HttpServletRequest request) {
        var values = request.getHeaders("Idempotency-Key");
        if (!values.hasMoreElements()) throw new CustomException(ErrorCode.INVALID_REQUEST);
        String value = values.nextElement();
        if (values.hasMoreElements() || value.isBlank() || value.length() > 200 || value.chars().anyMatch(Character::isISOControl))
            throw new CustomException(ErrorCode.INVALID_REQUEST);
        return value;
    }
}
