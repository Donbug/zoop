package com.zoop.graph.read;

import com.zoop.common.exception.CustomException;
import com.zoop.common.exception.ErrorCode;
import com.zoop.common.request.RequestIdFilter;
import jakarta.servlet.http.HttpServletRequest;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

/** OpenAPI {@code listCompanyDocuments}. */
@RestController
@RequestMapping("/api/v1/companies")
public class CompanyDocumentsController {
    private final CompanyDocumentsService service;

    public CompanyDocumentsController(CompanyDocumentsService service) { this.service = service; }

    @GetMapping("/{id}/documents")
    public CompanyDocumentsService.Response list(@PathVariable String id,
            @RequestParam(required = false) String kind, @RequestParam(required = false) String from,
            @RequestParam(required = false) String to, @RequestParam(required = false) String round,
            @RequestParam(required = false) String graphVersion, @RequestParam(required = false) String asOf,
            @RequestParam(required = false) String cursor, @RequestParam(required = false) String limit,
            HttpServletRequest request) {
        Integer parsedLimit = null;
        if (limit != null) {
            try {
                parsedLimit = Integer.valueOf(limit);
            } catch (NumberFormatException error) {
                throw new CustomException(ErrorCode.INVALID_REQUEST, error);
            }
        }
        return service.list(id, kind, from, to, round, graphVersion, asOf, cursor, parsedLimit,
                RequestIdFilter.currentId(request));
    }
}
