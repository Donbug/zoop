package com.zoop.company.controller;

import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.when;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

import com.zoop.auth.service.MemberSessionService;
import com.zoop.auth.service.MemberSessionService.MemberPrincipal;
import com.zoop.auth.service.SessionCookie;
import com.zoop.common.exception.CustomException;
import com.zoop.common.exception.ErrorCode;
import com.zoop.common.exception.GlobalExceptionHandler;
import com.zoop.common.request.RequestIdFilter;
import com.zoop.common.response.Metadata;
import com.zoop.company.service.CompanyDetailService;
import com.zoop.graph.read.PersonalCompanies;
import jakarta.servlet.http.Cookie;
import java.util.List;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.springframework.test.web.servlet.MockMvc;
import org.springframework.test.web.servlet.setup.MockMvcBuilders;

class CompanyDetailControllerTest {
    private static final String HYNIX = "KRX:000660";
    private final CompanyDetailService service = mock(CompanyDetailService.class);
    private final MemberSessionService sessions = mock(MemberSessionService.class);
    private final PersonalCompanies personal = mock(PersonalCompanies.class);
    private final MockMvc mvc = MockMvcBuilders.standaloneSetup(new CompanyDetailController(service, sessions, personal))
            .setControllerAdvice(new GlobalExceptionHandler()).addFilters(new RequestIdFilter()).build();

    @BeforeEach
    void setUp() {
        when(service.getCompany(eq(HYNIX), any(), any(), any(), any())).thenReturn(new CompanyDetailService.CompanyDetail(
                HYNIX, "SK하이닉스", null, null, null, null, null, "000660", List.of(), null, null, null, List.of(),
                List.of(), null, null, null, new Metadata("postgresql", null, null, "r", false, List.of())));
    }

    @Test
    void withoutASessionTheFlagsStayNull() throws Exception {
        mvc.perform(get("/api/v1/companies/" + HYNIX))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.holding").isEmpty())
                .andExpect(jsonPath("$.watch").isEmpty());
    }

    @Test
    void aMemberSeesTheirOwnHoldingAndWatchFlags() throws Exception {
        var member = new MemberPrincipal("m-1", "s-1");
        when(sessions.requireMember("member-token")).thenReturn(member);
        when(personal.of(member)).thenReturn(new PersonalCompanies.Ids(List.of(HYNIX), List.of("NASDAQ:NVDA")));
        mvc.perform(get("/api/v1/companies/" + HYNIX).cookie(new Cookie(SessionCookie.NAME, "member-token")))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.holding").value(true))
                .andExpect(jsonPath("$.watch").value(false));
    }

    @Test
    void aGuestSessionStillReadsThePublicPage() throws Exception {
        when(sessions.requireMember("guest-token")).thenThrow(new CustomException(ErrorCode.MEMBER_REQUIRED));
        mvc.perform(get("/api/v1/companies/" + HYNIX).cookie(new Cookie(SessionCookie.NAME, "guest-token")))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.holding").isEmpty());
    }
}
