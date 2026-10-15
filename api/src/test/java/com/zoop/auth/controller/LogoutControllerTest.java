package com.zoop.auth.controller;

import com.zoop.auth.service.MemberSessionService;
import com.zoop.common.request.RequestIdFilter;
import jakarta.servlet.http.Cookie;
import org.junit.jupiter.api.Test;
import org.springframework.test.web.servlet.setup.MockMvcBuilders;

import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.mock;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.header;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

class LogoutControllerTest {
    @Test
    void clearsOnlyTheMemberSessionCookieAndReturnsNoContent() throws Exception {
        var sessions = mock(MemberSessionService.class);
        var mvc = MockMvcBuilders.standaloneSetup(new LogoutController(sessions))
                .addFilters(new RequestIdFilter()).build();

        mvc.perform(post("/api/v1/auth/logout")
                        .cookie(new Cookie("zoop_session", "member-token")))
                .andExpect(status().isNoContent())
                .andExpect(header().string("Set-Cookie", org.hamcrest.Matchers.allOf(
                        org.hamcrest.Matchers.containsString("zoop_session="),
                        org.hamcrest.Matchers.containsString("Path=/api/v1"),
                        org.hamcrest.Matchers.containsString("Max-Age=0"))));

        verify(sessions).logoutMember("member-token");
    }
}
