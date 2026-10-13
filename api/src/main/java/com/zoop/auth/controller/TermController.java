package com.zoop.auth.controller;

import com.zoop.auth.dto.TermsResponse;
import com.zoop.auth.service.TermService;
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
    public TermsResponse listTerms(
            @RequestParam(required = false) String cursor,
            @RequestParam(required = false) Integer limit) {
        return service.list(cursor, limit);
    }
}
