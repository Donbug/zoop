package com.zoop.document.evidence.controller;

import com.zoop.common.request.RequestIdFilter;
import com.zoop.document.evidence.dto.EvidenceResponse;
import com.zoop.document.evidence.service.EvidenceService;
import io.swagger.v3.oas.annotations.Operation;
import jakarta.servlet.http.HttpServletRequest;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

/** {@code getEvidence}: public ({@code security: []}); access is decided by the current document and grant gates. */
@RestController
@RequestMapping("/api/v1/evidence")
public class EvidenceController {
    private final EvidenceService service;

    public EvidenceController(EvidenceService service) {
        this.service = service;
    }

    @GetMapping("/{id}")
    @Operation(summary = "공개 가능한 근거 조회",
            description = "문서 공개 상태와 현재 grant에 따라 접근을 결정합니다. 공개 경로이며 회원 쿠키 인증은 요구하지 않습니다.")
    public EvidenceResponse getEvidence(
            @PathVariable String id,
            @RequestParam(required = false) String round,
            @RequestParam(required = false) String graphVersion,
            @RequestParam(required = false) String asOf,
            @RequestParam(required = false) String companyId,
            HttpServletRequest request) {
        return service.read(id, round, graphVersion, asOf, companyId, RequestIdFilter.currentId(request));
    }
}
