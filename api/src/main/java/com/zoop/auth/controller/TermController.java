package com.zoop.auth.controller;

import com.zoop.auth.dto.TermsResponse;
import com.zoop.auth.service.TermService;
import io.swagger.v3.oas.annotations.Operation;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

@RestController
@RequestMapping("/api/v1/auth/terms")
public class TermController {
    private final TermService service;

    public TermController(TermService service) {
        this.service = service;
    }

    @GetMapping
    @Operation(summary = "현재 제공 가능한 약관 조회",
            description = "cursor와 limit은 선택 사항입니다. 약관 시행 전에는 body와 version이 null일 수 있습니다.")
    public TermsResponse listTerms(
            @RequestParam(required = false) String cursor,
            @RequestParam(required = false) Integer limit) {
        return service.list(cursor, limit);
    }
}
