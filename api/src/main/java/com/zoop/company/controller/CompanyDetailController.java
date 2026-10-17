package com.zoop.company.controller;

import com.zoop.auth.config.MemberAuthorizationInterceptor;
import com.zoop.auth.service.MemberSessionService;
import com.zoop.common.exception.CustomException;
import com.zoop.common.request.RequestIdFilter;
import com.zoop.company.service.CompanyDetailService;
import com.zoop.graph.read.PersonalCompanies;
import jakarta.servlet.http.HttpServletRequest;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

/** OpenAPI {@code getCompany}: public; holding/watch are filled only for a member session, null otherwise. */
@RestController
@RequestMapping("/api/v1/companies")
public class CompanyDetailController {
    private final CompanyDetailService service;
    private final MemberSessionService sessions;
    private final PersonalCompanies personalCompanies;

    public CompanyDetailController(CompanyDetailService service, MemberSessionService sessions,
            PersonalCompanies personalCompanies) {
        this.service = service;
        this.sessions = sessions;
        this.personalCompanies = personalCompanies;
    }

    @GetMapping("/{id}")
    public CompanyDetailService.CompanyDetail getCompany(@PathVariable String id,
            @RequestParam(required = false) String round,
            @RequestParam(required = false) String graphVersion,
            @RequestParam(required = false) String asOf,
            HttpServletRequest request) {
        var detail = service.getCompany(id, round, graphVersion, asOf, RequestIdFilter.currentId(request));
        PersonalCompanies.Ids mine;
        try {
            String token = MemberAuthorizationInterceptor.sessionToken(request);
            if (token == null) return detail;
            mine = personalCompanies.of(sessions.requireMember(token));
        } catch (CustomException notAMember) {
            // A guest, expired or ambiguous session still reads the public page, just without personal flags.
            return detail;
        }
        return detail.withPersonal(mine.holdings().contains(id), mine.watchlist().contains(id));
    }
}
