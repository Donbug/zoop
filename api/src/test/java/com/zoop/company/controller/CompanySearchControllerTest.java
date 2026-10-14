package com.zoop.company.controller;

import java.time.Instant;
import java.util.List;

import com.zoop.company.dto.CompanyListMetadata;
import com.zoop.company.dto.CompanyListResponse;
import com.zoop.company.dto.CompanySummaryResponse;
import com.zoop.company.service.CompanySearchApiService;
import com.zoop.common.exception.GlobalExceptionHandler;
import com.zoop.common.request.RequestIdFilter;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.springframework.test.web.servlet.MockMvc;
import org.springframework.test.web.servlet.setup.MockMvcBuilders;

import static org.mockito.ArgumentMatchers.*;
import static org.mockito.Mockito.*;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.*;

class CompanySearchControllerTest {
    private CompanySearchApiService service;
    private MockMvc mvc;

    @BeforeEach
    void setUp() {
        service = mock(CompanySearchApiService.class);
        mvc = MockMvcBuilders.standaloneSetup(new CompanySearchController(service))
                .setControllerAdvice(new GlobalExceptionHandler())
                .addFilters(new RequestIdFilter())
                .build();
    }

    @Test
    void exposesOpenApiCompanyListAndRequestMetadata() throws Exception {
        Instant asOf = Instant.parse("2026-10-14T01:00:00Z");
        when(service.search(eq("Zoop"), isNull(), eq(5), eq("graph-12"), eq(asOf), eq("req-company")))
                .thenReturn(new CompanyListResponse(
                        List.of(new CompanySummaryResponse("company-1", "Zoop", "ZOP", List.of("Zoop Corp"),
                                "Tech", "#123456", "/logos/zoop.svg", 3)),
                        new CompanyListMetadata("postgresql+neo4j", asOf, "graph-12", "req-company", false,
                                List.of()),
                        "opaque-next"));

        mvc.perform(get("/api/v1/companies")
                        .param("q", "Zoop")
                        .param("limit", "5")
                        .param("graphVersion", "graph-12")
                        .param("asOf", "2026-10-14T01:00:00Z")
                        .header(RequestIdFilter.HEADER, "req-company"))
                .andExpect(status().isOk())
                .andExpect(header().string(RequestIdFilter.HEADER, "req-company"))
                .andExpect(jsonPath("$.items[0].id").value("company-1"))
                .andExpect(jsonPath("$.items[0].issueCount").value(3))
                .andExpect(jsonPath("$.metadata.graphVersion").value("graph-12"))
                .andExpect(jsonPath("$.metadata.requestId").value("req-company"))
                .andExpect(jsonPath("$.metadata.partial").value(false))
                .andExpect(jsonPath("$.metadata.failures").isEmpty())
                .andExpect(jsonPath("$.nextCursor").value("opaque-next"));
    }

    @Test
    void rejectsNonPositiveLimitAsInvalidRequest() throws Exception {
        for (String limit : List.of("0", "-1")) {
            mvc.perform(get("/api/v1/companies").param("limit", limit))
                    .andExpect(status().isUnprocessableEntity())
                    .andExpect(jsonPath("$.error.code").value("INVALID_REQUEST"))
                    .andExpect(jsonPath("$.error.retryable").value(false));
        }
        verifyNoInteractions(service);
    }
}
