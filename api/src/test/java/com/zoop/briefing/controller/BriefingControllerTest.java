package com.zoop.briefing.controller;

import com.zoop.briefing.query.BriefingQueryService;
import com.zoop.briefing.storage.BriefingRoundRepository;
import com.zoop.common.exception.GlobalExceptionHandler;
import com.zoop.common.request.RequestIdFilter;
import java.time.Clock;
import java.time.Instant;
import java.time.ZoneOffset;
import java.util.List;
import java.util.Optional;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.springframework.test.web.servlet.MockMvc;
import org.springframework.test.web.servlet.setup.MockMvcBuilders;
import static org.mockito.Mockito.*;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.*;

class BriefingControllerTest {
    private MockMvc mvc;
    @BeforeEach void setup() {
        var repository = mock(BriefingRoundRepository.class);
        when(repository.find(any(), any())).thenReturn(Optional.empty());
        when(repository.history(null, null, 21)).thenReturn(List.of());
        var service = new BriefingQueryService(repository, Clock.fixed(Instant.parse("2026-10-13T02:00:00Z"), ZoneOffset.UTC), r -> false);
        mvc = MockMvcBuilders.standaloneSetup(new BriefingController(service))
            .setControllerAdvice(new GlobalExceptionHandler()).addFilters(new RequestIdFilter()).build();
    }
    @Test void publicEndpointReturnsContractWithoutAuthentication() throws Exception {
        mvc.perform(get("/api/v1/briefings").header("X-Request-ID", "current"))
            .andExpect(status().isOk()).andExpect(header().string("X-Request-ID", "current"))
            .andExpect(jsonPath("$.status").value("not_ready")).andExpect(jsonPath("$.metadata.requestId").value("current"))
            .andExpect(jsonPath("$.metadata.schedule.evening").value("17:30"));
        mvc.perform(get("/api/v1/briefings/rounds")).andExpect(status().isOk()).andExpect(jsonPath("$.items").isEmpty());
    }
    @Test void malformedInputsUseCommon422Contract() throws Exception {
        for (String query : List.of("?date=no-date", "?edition=no-edition", "?date=2026-02-30")) {
            mvc.perform(get("/api/v1/briefings" + query)).andExpect(status().isUnprocessableEntity())
                .andExpect(jsonPath("$.error.code").value("INVALID_REQUEST"));
        }
        mvc.perform(get("/api/v1/briefings/rounds?cursor=bad")).andExpect(status().isUnprocessableEntity())
            .andExpect(jsonPath("$.error.code").value("INVALID_CURSOR"));
        mvc.perform(get("/api/v1/briefings/rounds?limit=-1")).andExpect(status().isUnprocessableEntity());
    }
}
