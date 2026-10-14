package com.zoop.auth.controller;

import java.io.ByteArrayOutputStream;
import java.io.DataOutputStream;
import java.time.Clock;
import java.time.Instant;
import java.time.ZoneOffset;
import java.util.Base64;
import java.util.List;

import com.zoop.auth.repository.TermRepository;
import com.zoop.auth.repository.TermRow;
import com.zoop.auth.service.TermService;
import com.zoop.common.exception.GlobalExceptionHandler;
import com.zoop.common.request.RequestIdFilter;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.springframework.test.web.servlet.MockMvc;
import org.springframework.test.web.servlet.setup.MockMvcBuilders;

import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.header;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

class TermControllerTest {
    private MockMvc mvc;

    @BeforeEach
    void setUp() {
        TermRepository repository = (at, after, count) -> List.of(
                new TermRow("privacy", "개인정보 처리방침", true, null, null));
        var service = new TermService(repository,
                Clock.fixed(Instant.parse("2026-10-13T08:00:00Z"), ZoneOffset.UTC));
        mvc = MockMvcBuilders.standaloneSetup(new TermController(service))
                .setControllerAdvice(new GlobalExceptionHandler())
                .addFilters(new RequestIdFilter())
                .build();
    }

    @Test
    void publicTermsUseGoalResponseShapeAndRequestId() throws Exception {
        mvc.perform(get("/api/v1/auth/terms").header(RequestIdFilter.HEADER, "req-terms"))
                .andExpect(status().isOk())
                .andExpect(header().string(RequestIdFilter.HEADER, "req-terms"))
                .andExpect(jsonPath("$.items[0].id").value("privacy"))
                .andExpect(jsonPath("$.items[0].body").value((Object) null))
                .andExpect(jsonPath("$.items[0].version").value((Object) null))
                .andExpect(jsonPath("$.items[0].bodyAvailable").value(false))
                .andExpect(jsonPath("$.nextCursor").value((Object) null));
    }

    @Test
    void invalidCursorUsesApiErrorEnvelope() throws Exception {
        mvc.perform(get("/api/v1/auth/terms").param("cursor", "invalid!"))
                .andExpect(status().isUnprocessableEntity())
                .andExpect(jsonPath("$.error.code").value("INVALID_CURSOR"));
    }

    @Test
    void outOfRangeCursorTimestampUsesInvalidCursorInsteadOfInternalError() throws Exception {
        for (long epochSecond : List.of(Long.MIN_VALUE, Long.MAX_VALUE)) {
            mvc.perform(get("/api/v1/auth/terms")
                            .param("cursor", cursorWithTimestamp(epochSecond, 0)))
                    .andExpect(status().isUnprocessableEntity())
                    .andExpect(jsonPath("$.error.code").value("INVALID_CURSOR"));
        }
        mvc.perform(get("/api/v1/auth/terms")
                        .param("cursor", cursorWithTimestamp(Long.MAX_VALUE, Integer.MAX_VALUE)))
                .andExpect(status().isUnprocessableEntity())
                .andExpect(jsonPath("$.error.code").value("INVALID_CURSOR"));
    }

    private static String cursorWithTimestamp(long epochSecond, int nanos) throws Exception {
        var bytes = new ByteArrayOutputStream();
        var output = new DataOutputStream(bytes);
        output.writeByte(1);
        output.writeLong(epochSecond);
        output.writeInt(nanos);
        output.writeInt(1);
        output.writeUTF("privacy");
        return Base64.getUrlEncoder().withoutPadding().encodeToString(bytes.toByteArray());
    }
}
