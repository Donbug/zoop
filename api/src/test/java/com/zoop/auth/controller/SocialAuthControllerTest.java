package com.zoop.auth.controller;

import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

import com.zoop.auth.dto.SocialAuthorizationResponse;
import com.zoop.auth.service.AuthClientIpResolver;
import com.zoop.auth.service.SocialAuthService;
import org.junit.jupiter.api.Test;
import org.springframework.http.ResponseEntity;
import org.springframework.http.MediaType;
import org.springframework.test.web.servlet.setup.MockMvcBuilders;

class SocialAuthControllerTest {
    @Test
    void linkAuthorizationEndpointPassesSessionCsrfAndReturnPathToService() throws Exception {
        var service = mock(SocialAuthService.class);
        var ips = mock(AuthClientIpResolver.class);
        when(ips.resolve(org.mockito.ArgumentMatchers.any())).thenReturn("203.0.113.8");
        when(service.authorizeLink(anyString(), anyString(), anyString(), anyString(), anyString(), anyString()))
                .thenReturn(ResponseEntity.ok(new SocialAuthorizationResponse("https://accounts.example/authorize")));
        var mvc = MockMvcBuilders.standaloneSetup(new SocialAuthController(service, ips)).build();

        mvc.perform(post("/api/v1/auth/social/google/link/authorize")
                        .cookie(new jakarta.servlet.http.Cookie("zoop_oauth_pending", "P".repeat(43)),
                                new jakarta.servlet.http.Cookie("zoop_session", "S".repeat(43)))
                        .header("X-CSRF-Token", "C".repeat(43))
                        .contentType(MediaType.APPLICATION_JSON)
                        .content("{\"returnTo\":\"/\"}"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.authorizationUrl").value("https://accounts.example/authorize"));
        verify(service).authorizeLink(eq("google"), eq("/"), eq("203.0.113.8"), eq("P".repeat(43)),
                eq("S".repeat(43)), eq("C".repeat(43)));
    }
}
