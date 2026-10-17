package com.zoop.graph.read;

import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.ArgumentMatchers.isNull;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.when;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

import com.zoop.common.exception.CustomException;
import com.zoop.common.exception.ErrorCode;
import com.zoop.common.exception.GlobalExceptionHandler;
import com.zoop.common.request.RequestIdFilter;
import com.zoop.graph.read.dto.GraphResponse;
import java.util.List;
import org.junit.jupiter.api.Test;
import org.springframework.test.web.servlet.MockMvc;
import org.springframework.test.web.servlet.setup.MockMvcBuilders;

class GraphControllerTest {
    private final GraphQueryService service = mock(GraphQueryService.class);
    private final MockMvc mvc = MockMvcBuilders.standaloneSetup(new GraphController(service))
            .setControllerAdvice(new GlobalExceptionHandler()).addFilters(new RequestIdFilter()).build();

    @Test
    void responseKeepsEveryContractFieldIncludingNulls() throws Exception {
        var company = new GraphResponse.Node("KRX:000660", "company", "SK하이닉스", false, false, false, null, null,
                null, null, null, null, null, null);
        when(service.getGraph(eq("all"), isNull(), isNull(), isNull(), isNull(), isNull(), any())).thenReturn(
                new GraphResponse(List.of(company), List.of(), new GraphResponse.Metadata("public_graph_snapshot",
                        "2026-10-16T12:00:00Z", "fixture-2026-10-08", "all", false, "no_approved_issues", List.of(),
                        null, 500, "req-1", false, List.of(), null)));

        mvc.perform(get("/api/v1/graph").param("mode", "all").header("X-Request-ID", "req-1"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.nodes[0].kind").value("company"))
                .andExpect(jsonPath("$.nodes[0].brandColor").isEmpty())
                .andExpect(jsonPath("$.nodes[0].geography").hasJsonPath())
                .andExpect(jsonPath("$.metadata.graphVersion").value("fixture-2026-10-08"))
                .andExpect(jsonPath("$.metadata.depth").hasJsonPath())
                .andExpect(jsonPath("$.metadata.personalFilter").hasJsonPath())
                .andExpect(jsonPath("$.metadata.limit").value(500));
    }

    @Test
    void nonNumericDepthAndMissingVersionMapToContractErrors() throws Exception {
        mvc.perform(get("/api/v1/graph").param("depth", "two"))
                .andExpect(status().isUnprocessableContent())
                .andExpect(jsonPath("$.error.code").value("INVALID_REQUEST"));
        when(service.getGraph(any(), any(), any(), any(), eq("v-missing"), any(), any()))
                .thenThrow(new CustomException(ErrorCode.VERSION_UNAVAILABLE));
        mvc.perform(get("/api/v1/graph").param("graphVersion", "v-missing"))
                .andExpect(status().isConflict())
                .andExpect(jsonPath("$.error.code").value("VERSION_UNAVAILABLE"));
    }
}
