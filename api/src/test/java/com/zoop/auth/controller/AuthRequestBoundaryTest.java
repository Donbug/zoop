package com.zoop.auth.controller;

import com.zoop.auth.config.AuthOriginInterceptor;
import com.zoop.auth.service.AuthOriginPolicy;
import com.zoop.auth.service.RateLimitedException;
import com.zoop.common.exception.GlobalExceptionHandler;
import com.zoop.common.request.RequestIdFilter;
import org.junit.jupiter.api.Test;
import org.springframework.test.web.servlet.setup.MockMvcBuilders;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RestController;

import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.header;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

class AuthRequestBoundaryTest {
    @Test
    void originIsCheckedBeforeHandlerAndRateErrorHasRetryAfter() throws Exception {
        var mvc = MockMvcBuilders.standaloneSetup(new StubAuthController())
                .addInterceptors(new AuthOriginInterceptor(new AuthOriginPolicy("https://zoop.example")))
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
        mvc.perform(post("/api/v1/auth/signup")
                        .header("Origin", "https://zoop.example"))
                .andExpect(status().isOk());
        mvc.perform(post("/api/v1/auth/login")
                        .header("Origin", "https://zoop.example"))
                .andExpect(status().isTooManyRequests())
                .andExpect(header().string("Retry-After", "17"))
                .andExpect(jsonPath("$.error.code").value("RATE_LIMITED"));
    }

    @RestController
    static class StubAuthController {
        @PostMapping("/api/v1/auth/signup")
        void signup() {
        }

        @PostMapping("/api/v1/auth/login")
        void login() {
            throw new RateLimitedException(17);
        }
    }
}
