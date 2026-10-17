package com.zoop.auth.controller;

import java.time.Instant;

import com.zoop.auth.config.MemberAuthorizationInterceptor;
import com.zoop.auth.dto.SessionResponse;
import com.zoop.auth.service.MemberSessionService;
import com.zoop.auth.service.MemberSettingsService;
import com.zoop.auth.service.SessionCookie;
import com.zoop.common.exception.GlobalExceptionHandler;
import com.zoop.common.request.RequestIdFilter;
import jakarta.servlet.http.Cookie;
import org.junit.jupiter.api.Test;
import org.springframework.http.MediaType;
import org.springframework.test.web.servlet.setup.MockMvcBuilders;

import static org.mockito.Mockito.*;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.put;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

class TutorialControllerTest {
    private static final String TOKEN = "t".repeat(43);
    private static final MemberSessionService.MemberPrincipal MEMBER =
            new MemberSessionService.MemberPrincipal("member-1", "session-1");

    @Test
    void storesExactTargetStateAndReturnsRefreshedSession() throws Exception {
        var settings = mock(MemberSettingsService.class);
        var sessions = mock(MemberSessionService.class);
        var response = new SessionResponse(true, "member",
                new SessionResponse.User("member-1", "member@zoop.test", "Member"),
                new SessionResponse.Setup(true, true),
                SessionResponse.metadata(Instant.parse("2026-10-17T00:00:00Z"), "tutorial-request"),
                "c".repeat(43), Instant.parse("2026-10-17T12:00:00Z"));
        when(sessions.lookup(TOKEN, "tutorial-request"))
                .thenReturn(new MemberSessionService.SessionLookup(response, false));
        var mvc = MockMvcBuilders.standaloneSetup(new TutorialController(settings, sessions))
                .setControllerAdvice(new GlobalExceptionHandler())
                .addFilters(new RequestIdFilter()).build();

        mvc.perform(put("/api/v1/auth/tutorial")
                        .requestAttr(MemberAuthorizationInterceptor.PRINCIPAL_ATTRIBUTE, MEMBER)
                        .cookie(new Cookie(SessionCookie.NAME, TOKEN))
                        .header("X-Request-ID", "tutorial-request")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content("{\"completed\":true}"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.kind").value("member"))
                .andExpect(jsonPath("$.setup.completed").value(true))
                .andExpect(jsonPath("$.setup.tutorialCompleted").value(true))
                .andExpect(jsonPath("$.metadata.requestId").value("tutorial-request"));

        verify(settings).setTutorialCompleted(MEMBER, true, "tutorial-request");
        verify(sessions).lookup(TOKEN, "tutorial-request");
    }

    @Test
    void rejectsMissingNullWrongTypeAndUnknownFields() throws Exception {
        var settings = mock(MemberSettingsService.class);
        var sessions = mock(MemberSessionService.class);
        var mvc = MockMvcBuilders.standaloneSetup(new TutorialController(settings, sessions))
                .setControllerAdvice(new GlobalExceptionHandler())
                .addFilters(new RequestIdFilter()).build();

        for (String body : new String[]{"{}", "{\"completed\":null}", "{\"completed\":1}",
                "{\"completed\":true,\"extra\":1}"}) {
            mvc.perform(put("/api/v1/auth/tutorial")
                            .requestAttr(MemberAuthorizationInterceptor.PRINCIPAL_ATTRIBUTE, MEMBER)
                            .cookie(new Cookie(SessionCookie.NAME, TOKEN))
                            .contentType(MediaType.APPLICATION_JSON).content(body))
                    .andExpect(status().isUnprocessableContent())
                    .andExpect(jsonPath("$.error.code").value("INVALID_REQUEST"));
        }

        verifyNoInteractions(settings, sessions);
    }
}
