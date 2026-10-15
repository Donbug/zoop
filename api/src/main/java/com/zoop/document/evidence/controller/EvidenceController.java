package com.zoop.document.evidence.controller;

import com.zoop.common.request.RequestIdFilter;
import com.zoop.document.evidence.dto.EvidenceResponse;
import com.zoop.document.evidence.service.EvidenceService;
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
