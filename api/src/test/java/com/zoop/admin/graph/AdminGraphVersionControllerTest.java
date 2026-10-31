package com.zoop.admin.graph;

import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.ArgumentMatchers.argThat;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.verifyNoInteractions;
import static org.mockito.Mockito.when;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

import com.zoop.admin.auth.config.AdminAuthorizationInterceptor;
import com.zoop.admin.auth.service.AdminPrincipal;
import com.zoop.admin.graph.GraphVersionAdminResponse.ActivateResponse;
import com.zoop.common.exception.GlobalExceptionHandler;
import com.zoop.common.request.RequestIdFilter;
import org.junit.jupiter.api.Test;
import org.springframework.http.MediaType;
import org.springframework.test.web.servlet.MockMvc;
import org.springframework.test.web.servlet.request.MockHttpServletRequestBuilder;
import org.springframework.test.web.servlet.setup.MockMvcBuilders;

/**
 * activateGraphVersion over HTTP (PR #275 review 3): {@code expectedActiveVersionId} is required but nullable, so a body without
 * it is 422 before the service runs, while an explicit null reaches the service as "none was active".
 */
class AdminGraphVersionControllerTest {
    private static final AdminPrincipal ADMIN = new AdminPrincipal("admin-1", "admin@example.com", "Admin", "admin", "s-1");

    private final AdminGraphVersionService service = mock(AdminGraphVersionService.class);
    private final MockMvc mvc = MockMvcBuilders.standaloneSetup(new AdminGraphVersionController(service))
            .setControllerAdvice(new GlobalExceptionHandler()).addFilters(new RequestIdFilter()).build();

    private static MockHttpServletRequestBuilder activate(String body) {
        return post("/api/v1/admin/graph/versions/gv-1/activate").contentType(MediaType.APPLICATION_JSON)
                .header("Idempotency-Key", "key-1").requestAttr(AdminAuthorizationInterceptor.PRINCIPAL_ATTRIBUTE, ADMIN)
                .content(body);
    }

    @Test
    void aBodyWithoutExpectedActiveVersionIdIsInvalidBeforeTheServiceRuns() throws Exception {
        mvc.perform(activate("{\"reason\":\"go live\"}"))
                .andExpect(status().isUnprocessableContent())
                .andExpect(jsonPath("$.error.code").value("INVALID_REQUEST"));
        verifyNoInteractions(service);
    }

    @Test
    void anExplicitNullMeansNoneWasActiveAndReachesTheService() throws Exception {
        when(service.activate(eq("gv-1"), any(), eq("key-1"), eq(ADMIN), anyString()))
                .thenReturn(new ActivateResponse("gv-1", null, false));

        mvc.perform(activate("{\"reason\":\"go live\",\"expectedActiveVersionId\":null}"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.activeVersionId").value("gv-1"))
                .andExpect(jsonPath("$.previousActiveVersionId").hasJsonPath());
        verify(service).activate(eq("gv-1"),
                argThat(r -> r.expectedActiveVersionId() == null && "forward".equals(r.mode())), eq("key-1"),
                eq(ADMIN), anyString());
    }

    @Test
    void aValueIsPassedThroughAndAMissingIdempotencyKeyIsInvalid() throws Exception {
        when(service.activate(eq("gv-1"), any(), eq("key-1"), eq(ADMIN), anyString()))
                .thenReturn(new ActivateResponse("gv-1", "gv-0", false));

        mvc.perform(activate("{\"reason\":\"go live\",\"expectedActiveVersionId\":\"gv-0\"}"))
                .andExpect(status().isOk());
        verify(service).activate(eq("gv-1"), argThat(r -> "gv-0".equals(r.expectedActiveVersionId())), eq("key-1"),
                eq(ADMIN), anyString());

        mvc.perform(post("/api/v1/admin/graph/versions/gv-1/activate").contentType(MediaType.APPLICATION_JSON)
                        .requestAttr(AdminAuthorizationInterceptor.PRINCIPAL_ATTRIBUTE, ADMIN)
                        .content("{\"reason\":\"go live\",\"expectedActiveVersionId\":null}"))
                .andExpect(status().isUnprocessableContent())
                .andExpect(jsonPath("$.error.code").value("INVALID_REQUEST"));
    }

    @Test
    void rollbackReachesTheServiceAsAnExplicitMode() throws Exception {
        when(service.activate(eq("gv-1"), any(), eq("key-1"), eq(ADMIN), anyString()))
                .thenReturn(new ActivateResponse("gv-1", "gv-2", false));

        mvc.perform(activate("{\"reason\":\"restore\",\"expectedActiveVersionId\":\"gv-2\",\"mode\":\"rollback\"}"))
                .andExpect(status().isOk());
        verify(service).activate(eq("gv-1"), argThat(r -> "rollback".equals(r.mode())), eq("key-1"),
                eq(ADMIN), anyString());
    }

    @Test
    void anUnknownActivationModeIsInvalidBeforeTheServiceRuns() throws Exception {
        mvc.perform(activate("{\"reason\":\"go live\",\"expectedActiveVersionId\":null,\"mode\":\"replace\"}"))
                .andExpect(status().isUnprocessableContent())
                .andExpect(jsonPath("$.error.code").value("INVALID_REQUEST"));
        verifyNoInteractions(service);
    }
}
