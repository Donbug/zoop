package com.zoop.auth.controller;

import java.time.Instant;
import com.zoop.auth.dto.SessionResponse;
import com.zoop.auth.service.MemberSessionService;
import com.zoop.auth.service.SessionCookie;
import com.zoop.common.request.RequestIdFilter;
import jakarta.servlet.http.Cookie;
import org.junit.jupiter.api.Test;
import org.springframework.test.web.servlet.setup.MockMvcBuilders;

import static org.mockito.Mockito.*;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.*;

class GuestSessionControllerTest {
    @Test
    void startsGuestAndSetsSecureSessionCookie() throws Exception {
        var sessions = mock(MemberSessionService.class);
        var response = new SessionResponse(true, "guest", null,
                new SessionResponse.Setup(false, false),
                SessionResponse.metadata(Instant.parse("2026-10-15T00:00:00Z"), "guest-request"),
                "c".repeat(43), Instant.parse("2026-10-15T12:00:00Z"));
        when(sessions.issueGuest("g".repeat(43), "guest-request"))
                .thenReturn(new MemberSessionService.IssuedSession("n".repeat(43), response));
        var mvc = MockMvcBuilders.standaloneSetup(new GuestSessionController(sessions))
                .addFilters(new RequestIdFilter()).build();

        mvc.perform(post("/api/v1/auth/guest").header("X-Request-ID", "guest-request")
                        .cookie(new Cookie(SessionCookie.NAME, "g".repeat(43))))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.kind").value("guest"))
                .andExpect(jsonPath("$.authenticated").value(true))
                .andExpect(jsonPath("$.user").value((Object) null))
                .andExpect(jsonPath("$.setup.completed").value(false))
                .andExpect(jsonPath("$.setup.tutorialCompleted").value(false))
                .andExpect(header().string("Set-Cookie", org.hamcrest.Matchers.allOf(
                        org.hamcrest.Matchers.containsString("zoop_session=" + "n".repeat(43)),
                        org.hamcrest.Matchers.containsString("HttpOnly"),
                        org.hamcrest.Matchers.containsString("Secure"),
                        org.hamcrest.Matchers.containsString("SameSite=Lax"),
                        org.hamcrest.Matchers.containsString("Max-Age=43200"))));
        verify(sessions).issueGuest("g".repeat(43), "guest-request");
    }
}
