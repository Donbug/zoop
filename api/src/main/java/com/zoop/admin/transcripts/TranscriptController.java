package com.zoop.admin.transcripts;

import com.zoop.admin.auth.config.AdminAuthorizationInterceptor;
import com.zoop.admin.auth.service.AdminPrincipal;
import com.zoop.common.exception.CustomException;
import com.zoop.common.exception.ErrorCode;
import com.zoop.common.request.RequestIdFilter;
import io.swagger.v3.oas.annotations.Operation;
import io.swagger.v3.oas.annotations.media.Content;
import io.swagger.v3.oas.annotations.media.Schema;
import io.swagger.v3.oas.annotations.responses.ApiResponse;
import jakarta.servlet.http.HttpServletRequest;
import jakarta.servlet.http.HttpServletResponse;
import org.springframework.web.bind.annotation.*;

/** A-ADM-02b / WBS6.10.11: member chat execution is not called by administrator reads. */
@RestController
@RequestMapping("/api/v1/admin/transcripts")
public class TranscriptController {
    private final TranscriptService service;
    public TranscriptController(TranscriptService service) { this.service = service; }

    @GetMapping
    @Operation(operationId = "listMaskedTranscripts", summary = "권한·목적·마스킹·감사 확인 후 대화록 목록")
    @ApiResponse(responseCode = "200", content = @Content(schema = @Schema(implementation = TranscriptHttpSchemas.Page.class)))
    public TranscriptHttpSchemas.Page list(@RequestParam(required = false) String purpose,
            @RequestParam(required = false) String only, @RequestParam(required = false) String cursor,
            @RequestParam(required = false) Integer limit, HttpServletRequest request, HttpServletResponse response) {
        response.setHeader("Cache-Control", "no-store");
        return service.list(admin(request), purpose, only, cursor, limit, RequestIdFilter.currentId(request));
    }

    @GetMapping("/{session_id}")
    @Operation(operationId = "getMaskedTranscript", summary = "권한·목적·마스킹·감사 확인 후 대화록 상세")
    @ApiResponse(responseCode = "200", content = @Content(schema = @Schema(implementation = TranscriptHttpSchemas.Detail.class)))
    public TranscriptHttpSchemas.Detail detail(@PathVariable("session_id") String sessionId,
            @RequestParam(required = false) String purpose, HttpServletRequest request, HttpServletResponse response) {
        response.setHeader("Cache-Control", "no-store");
        return service.detail(admin(request), purpose, sessionId, RequestIdFilter.currentId(request));
    }
    private static AdminPrincipal admin(HttpServletRequest request) {
        if (request.getAttribute(AdminAuthorizationInterceptor.PRINCIPAL_ATTRIBUTE) instanceof AdminPrincipal admin) return admin;
        throw new CustomException(ErrorCode.AUTH_REQUIRED);
    }
}
