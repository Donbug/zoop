package com.zoop.graph.read;

import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.when;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

import com.zoop.common.exception.GlobalExceptionHandler;
import com.zoop.common.request.RequestIdFilter;
import com.zoop.document.evidence.service.EvidenceService;
import com.zoop.document.repository.DocumentRegistryRepository;
import java.time.Instant;
import java.util.Optional;
import org.junit.jupiter.api.Test;
import org.springframework.jdbc.core.namedparam.NamedParameterJdbcTemplate;
import org.springframework.test.web.servlet.MockMvc;
import org.springframework.test.web.servlet.setup.MockMvcBuilders;
import tools.jackson.databind.json.JsonMapper;

/** getEvent over HTTP: every contract key is on the wire (nulls included) and the failures keep their status. */
class EventControllerTest {
    private final MockMvc mvc;

    EventControllerTest() {
        PublicGraphReader reader = GraphReadFixtures.reader(Instant.parse("2026-10-16T12:00:00Z"), () -> DisclosureExclusions.NONE);
        DocumentRegistryRepository registry = mock(DocumentRegistryRepository.class);
        when(registry.findVersion(anyString(), anyString())).thenReturn(Optional.empty());
        mvc = MockMvcBuilders.standaloneSetup(new EventController(
                        new EventListService(reader, mock(NamedParameterJdbcTemplate.class), JsonMapper.builder().build()),
                        new EventDetailService(reader, mock(EvidenceService.class), registry)))
                .setControllerAdvice(new GlobalExceptionHandler()).addFilters(new RequestIdFilter()).build();
    }

    @Test
    void eventDetailKeepsEveryContractFieldIncludingNulls() throws Exception {
        mvc.perform(get("/api/v1/events/iss-fixture-euv-export"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.id").value("iss-fixture-euv-export"))
                .andExpect(jsonPath("$.approval").hasJsonPath())
                .andExpect(jsonPath("$.summary.status").value("unavailable"))
                .andExpect(jsonPath("$.sourceSupport.knownLineageCount").hasJsonPath())
                .andExpect(jsonPath("$.sourceSupport.independentSourceCount").hasJsonPath())
                .andExpect(jsonPath("$.articles[0].publisher").hasJsonPath())
                .andExpect(jsonPath("$.articles[0].relationType").hasJsonPath())
                .andExpect(jsonPath("$.relations[0].edgeId").isString())
                .andExpect(jsonPath("$.follows.previous").isArray())
                .andExpect(jsonPath("$.mentions").isArray())
                .andExpect(jsonPath("$.fieldDecisions").isArray())
                .andExpect(jsonPath("$.metadata.graphVersion").value("fixture-2026-10-08"))
                .andExpect(jsonPath("$.metadata.partial").value(true));
    }

    @Test
    void unknownEventIsNotFoundAndABadAsOfIsInvalid() throws Exception {
        mvc.perform(get("/api/v1/events/iss-unknown"))
                .andExpect(status().isNotFound())
                .andExpect(jsonPath("$.error.code").value("RESOURCE_NOT_FOUND"));
        mvc.perform(get("/api/v1/events/iss-fixture-euv-export").param("asOf", "yesterday"))
                .andExpect(status().isUnprocessableContent())
                .andExpect(jsonPath("$.error.code").value("INVALID_REQUEST"));
        mvc.perform(get("/api/v1/events/iss-fixture-euv-export").param("round", "brf-2026-09-17-morning"))
                .andExpect(status().isConflict())
                .andExpect(jsonPath("$.error.code").value("VERSION_UNAVAILABLE"));
    }
}
