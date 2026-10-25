package com.zoop.graph.read;

import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

import com.zoop.common.exception.GlobalExceptionHandler;
import com.zoop.common.request.RequestIdFilter;
import java.time.Instant;
import org.junit.jupiter.api.Test;
import org.springframework.test.web.servlet.MockMvc;
import org.springframework.test.web.servlet.setup.MockMvcBuilders;

class GraphRelationControllerTest {
    private final MockMvc mvc = MockMvcBuilders.standaloneSetup(new GraphRelationController(new GraphRelationService(
                    GraphReadFixtures.reader(Instant.parse("2026-10-16T12:00:00Z"), pinned -> DisclosureExclusions.NONE),
                    org.mockito.Mockito.mock(org.springframework.jdbc.core.namedparam.NamedParameterJdbcTemplate.class))))
            .setControllerAdvice(new GlobalExceptionHandler()).addFilters(new RequestIdFilter()).build();

    @Test
    void edgeDetailKeepsEveryContractFieldIncludingNulls() throws Exception {
        String id = DisplayGraph.edgeId("STRUCTURALLY_RELATED_TO", GraphReadFixtures.HBM_EQUIP, GraphReadFixtures.HYNIX);
        mvc.perform(get("/api/v1/graph/edges/" + id))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.source.kind").value("issue"))
                .andExpect(jsonPath("$.source.logoUrl").hasJsonPath())
                .andExpect(jsonPath("$.target.brandColor").hasJsonPath())
                .andExpect(jsonPath("$.verification.status").value("ALLOW"))
                .andExpect(jsonPath("$.verification.note").hasJsonPath())
                .andExpect(jsonPath("$.basis[0].edgeId").value("basis-fixture-04"))
                .andExpect(jsonPath("$.basis[0].validUntil").hasJsonPath())
                .andExpect(jsonPath("$.metadata.failures").isArray());
    }

    @Test
    void unknownEdgeIsNotFound() throws Exception {
        mvc.perform(get("/api/v1/graph/edges/edge-0000000000000000"))
                .andExpect(status().isNotFound())
                .andExpect(jsonPath("$.error.code").value("RESOURCE_NOT_FOUND"));
    }
}
