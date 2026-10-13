package com.zoop.briefing.controller;

import java.time.LocalDate;
import jakarta.servlet.http.HttpServletRequest;
import org.springframework.format.annotation.DateTimeFormat;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;
import com.zoop.briefing.query.BriefingQueryService;
import com.zoop.common.request.RequestIdFilter;
import tools.jackson.databind.node.ObjectNode;

@RestController
@RequestMapping("/api/v1/briefings")
public class BriefingController {
    private final BriefingQueryService service;
    public BriefingController(BriefingQueryService service) { this.service = service; }

    @GetMapping
    public ObjectNode getBriefing(@RequestParam(required = false) @DateTimeFormat(iso = DateTimeFormat.ISO.DATE) LocalDate date,
            @RequestParam(required = false) String edition, HttpServletRequest request) {
        return service.get(date, edition, RequestIdFilter.currentId(request));
    }
    @GetMapping("/rounds")
    public ObjectNode listBriefingRounds(@RequestParam(required = false) String cursor, @RequestParam(required = false) Integer limit) {
        return service.history(cursor, limit);
    }
}
