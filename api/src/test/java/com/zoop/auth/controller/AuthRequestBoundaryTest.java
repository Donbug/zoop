package com.zoop.auth.controller;

import com.zoop.auth.config.AuthOriginInterceptor;
import com.zoop.auth.dto.SignupRequest;
import com.zoop.auth.service.AuthOriginPolicy;
import com.zoop.auth.service.AuthClientIpResolver;
import com.zoop.auth.service.AuthRateLimiter;
import com.zoop.auth.service.RateLimitedException;
import com.zoop.common.exception.GlobalExceptionHandler;
import com.zoop.common.request.RequestIdFilter;
import org.junit.jupiter.api.Test;
import org.springframework.test.web.servlet.setup.MockMvcBuilders;
import org.springframework.http.MediaType;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RestController;

import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.header;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;
import static org.mockito.Mockito.*;

class AuthRequestBoundaryTest {
    @Test
    void originIsCheckedBeforeHandlerAndRateErrorHasRetryAfter() throws Exception {
        var rates = mock(AuthRateLimiter.class);
        var mvc = MockMvcBuilders.standaloneSetup(new StubAuthController())
                .addInterceptors(new AuthOriginInterceptor(new AuthOriginPolicy("https://zoop.example"),
                        new AuthClientIpResolver(""), rates))
                .setControllerAdvice(new GlobalExceptionHandler())
                .addFilters(new RequestIdFilter())
                .build();

        mvc.perform(post("/api/v1/auth/signup").header("X-Request-ID", "request-1"))
                .andExpect(status().isForbidden())
                .andExpect(jsonPath("$.error.code").value("ACCESS_DENIED"))
                .andExpect(jsonPath("$.error.requestId").value("request-1"));
        mvc.perform(post("/api/v1/auth/signup")
                        .header("Origin", "https://zoop.example.evil"))
                .andExpect(status().isForbidden());
        verifyNoInteractions(rates);
        mvc.perform(post("/api/v1/auth/signup")
                        .header("Origin", "https://zoop.example")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content("{\"email\":\"user@example.com\"}"))
                .andExpect(status().isOk());
        verify(rates).recordSignupIpAttempt("127.0.0.1");
        mvc.perform(post("/api/v1/auth/signup")
                        .header("Origin", "https://zoop.example")
                        .contentType(MediaType.APPLICATION_JSON).content("{"))
                .andExpect(status().isUnprocessableEntity())
                .andExpect(jsonPath("$.error.code").value("INVALID_REQUEST"));
        verify(rates, times(2)).recordSignupIpAttempt("127.0.0.1");
        mvc.perform(post("/api/v1/auth/social/signup")
                        .header("Origin", "https://zoop.example")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content("{\"agreements\":[]}"))
                .andExpect(status().isOk());
        verify(rates, times(3)).recordSignupIpAttempt("127.0.0.1");
        mvc.perform(post("/api/v1/auth/social/google/link/authorize")
                        .contentType(MediaType.APPLICATION_JSON).content("{}"))
                .andExpect(status().isForbidden());
        mvc.perform(post("/api/v1/auth/social/google/link/authorize")
                        .header("Origin", "https://zoop.example")
                        .contentType(MediaType.APPLICATION_JSON).content("{}"))
                .andExpect(status().isOk());
        mvc.perform(post("/api/v1/auth/login")
                        .header("Origin", "https://zoop.example"))
                .andExpect(status().isTooManyRequests())
                .andExpect(header().string("Retry-After", "17"))
                .andExpect(jsonPath("$.error.code").value("RATE_LIMITED"));
        verify(rates).recordLoginIpAttempt("127.0.0.1");
    }

    @RestController
    static class StubAuthController {
        @PostMapping("/api/v1/auth/signup")
        void signup(@RequestBody SignupRequest body) {
        }

        @PostMapping("/api/v1/auth/login")
        void login() {
            throw new RateLimitedException(17);
        }

        @PostMapping("/api/v1/auth/social/signup")
        void socialSignup() {
        }

        @PostMapping("/api/v1/auth/social/google/link/authorize")
        void linkSocial() {
        }
    }
}
