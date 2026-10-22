package com.zoop.graph.read;

import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.when;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.header;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

import com.zoop.common.exception.CustomException;
import com.zoop.common.exception.ErrorCode;
import com.zoop.common.exception.GlobalExceptionHandler;
import com.zoop.common.request.RequestIdFilter;
import com.zoop.common.response.Metadata;
import java.time.Instant;
import java.util.List;
import org.junit.jupiter.api.Test;
import org.springframework.test.web.servlet.MockMvc;
import org.springframework.test.web.servlet.setup.MockMvcBuilders;

class CompanyDocumentsControllerTest {
    private final CompanyDocumentsService service = mock(CompanyDocumentsService.class);
    private final MockMvc mvc = MockMvcBuilders.standaloneSetup(new CompanyDocumentsController(service))
            .setControllerAdvice(new GlobalExceptionHandler()).addFilters(new RequestIdFilter()).build();

    @Test
    void publicResponseUsesTheContractShapeAndRequestId() throws Exception {
        when(service.list(eq("KRX:000660"), any(), any(), any(), any(), any(), any(), any(), eq(3), any()))
                .thenAnswer(call -> new CompanyDocumentsService.Response(List.of(
                        new CompanyDocumentsService.Document("art-1", "제목", "출처", null, null, "news",
                                List.of(), List.of(), null, "v1", null, null, null, null)),
                        new Metadata("public_graph_snapshot", Instant.parse("2026-10-16T12:00:00Z"), "fixture-1",
                                call.getArgument(9), false, List.of()), null));
        mvc.perform(get("/api/v1/companies/KRX:000660/documents?limit=3"))
                .andExpect(status().isOk())
                .andExpect(header().exists("X-Request-ID"))
                .andExpect(jsonPath("$.items[0].id").value("art-1"))
                .andExpect(jsonPath("$.items[0].sentiment").isEmpty())
                .andExpect(jsonPath("$.items[0].quotes").isArray())
                .andExpect(jsonPath("$.metadata.graphVersion").value("fixture-1"))
                .andExpect(jsonPath("$.nextCursor").isEmpty());
    }

    @Test
    void unsupportedRoundUsesVersionUnavailable() throws Exception {
        when(service.list(eq("KRX:000660"), any(), any(), any(), eq("brf-1"), any(), any(), any(), any(), any()))
                .thenThrow(new CustomException(ErrorCode.VERSION_UNAVAILABLE));
        mvc.perform(get("/api/v1/companies/KRX:000660/documents?round=brf-1"))
                .andExpect(status().isConflict())
                .andExpect(jsonPath("$.error.code").value("VERSION_UNAVAILABLE"));
    }

    @Test
    void nonNumericLimitIsAnInvalidRequest() throws Exception {
        mvc.perform(get("/api/v1/companies/KRX:000660/documents?limit=three"))
                .andExpect(status().isUnprocessableEntity())
                .andExpect(jsonPath("$.error.code").value("INVALID_REQUEST"));
    }
}
