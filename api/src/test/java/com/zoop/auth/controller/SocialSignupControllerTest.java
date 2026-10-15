package com.zoop.auth.controller;

import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.ArgumentMatchers.isNull;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.header;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

import java.time.Instant;
import java.util.Optional;
import org.junit.jupiter.api.Assertions;

import com.zoop.auth.dto.SessionResponse;
import com.zoop.auth.service.MemberSessionService;
import com.zoop.auth.service.SocialSignupService;
import com.zoop.common.exception.GlobalExceptionHandler;
import com.zoop.common.request.RequestIdFilter;
import org.junit.jupiter.api.Test;
import org.springframework.http.MediaType;
import org.springframework.test.web.servlet.setup.MockMvcBuilders;

class SocialSignupControllerTest {
    @Test
    void successReturnsMemberSessionAndClearsOAuthPendingCookie() throws Exception {
        var service = mock(SocialSignupService.class);
        var issued = new MemberSessionService.IssuedSession("S".repeat(43),
                new SessionResponse(true, "member", new SessionResponse.User("member-id", "member@example.com", "회원"),
                        new SessionResponse.Setup(false, false),
                        SessionResponse.metadata(Instant.parse("2026-10-15T00:00:00Z"), "request-1"),
                        "C".repeat(43), Instant.parse("2026-10-15T12:00:00Z")));
        when(service.signup(any(), anyString(), anyString(), anyString())).thenReturn(Optional.of(issued));
        var mvc = MockMvcBuilders.standaloneSetup(new SocialSignupController(service))
                .setControllerAdvice(new GlobalExceptionHandler()).addFilters(new RequestIdFilter()).build();

        mvc.perform(post("/api/v1/auth/social/signup").header("X-Request-ID", "request-1")
                        .cookie(new jakarta.servlet.http.Cookie("zoop_oauth_pending", "P".repeat(43)),
                                new jakarta.servlet.http.Cookie("zoop_session", "O".repeat(43)))
                        .contentType(MediaType.APPLICATION_JSON)
                        .content("{\"agreements\":[]}"))
                .andExpect(status().isCreated())
                .andExpect(header().exists("Set-Cookie"))
                .andExpect(jsonPath("$.authenticated").value(true))
                .andExpect(result -> Assertions.assertEquals(2,
                        result.getResponse().getHeaders("Set-Cookie").size()));

        org.mockito.ArgumentCaptor<String> previousSession = org.mockito.ArgumentCaptor.forClass(String.class);
        verify(service).signup(any(), org.mockito.ArgumentMatchers.eq("P".repeat(43)),
                previousSession.capture(), org.mockito.ArgumentMatchers.eq("request-1"));
        org.junit.jupiter.api.Assertions.assertEquals("O".repeat(43), previousSession.getValue());
    }

    @Test
    void accountCollisionUsesTheSocialLinkErrorContract() throws Exception {
        var service = mock(SocialSignupService.class);
        when(service.signup(any(), anyString(), isNull(), anyString())).thenReturn(Optional.empty());
        var mvc = MockMvcBuilders.standaloneSetup(new SocialSignupController(service))
                .setControllerAdvice(new GlobalExceptionHandler()).addFilters(new RequestIdFilter()).build();

        mvc.perform(post("/api/v1/auth/social/signup").header("X-Request-ID", "request-2")
                        .cookie(new jakarta.servlet.http.Cookie("zoop_oauth_pending", "P".repeat(43)))
                        .contentType(MediaType.APPLICATION_JSON).content("{\"agreements\":[]}"))
                .andExpect(status().isConflict())
                .andExpect(jsonPath("$.error.code").value("SOCIAL_LINK_REQUIRED"));
    }
}
