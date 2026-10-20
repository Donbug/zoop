package com.zoop.briefing.query;

import com.zoop.briefing.controller.BriefingController;
import com.zoop.briefing.controller.BriefingReadExceptionHandler;
import com.zoop.common.exception.GlobalExceptionHandler;
import com.zoop.common.request.RequestIdFilter;
import org.junit.jupiter.api.Test;
import org.springframework.test.web.servlet.setup.MockMvcBuilders;
import org.springframework.transaction.CannotCreateTransactionException;

import static org.mockito.Mockito.*;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.*;

class BriefingTransactionFailureTest {
    @Test void transactionAcquisitionFailureUsesTheCommonUnavailableContract() throws Exception {
        var service = mock(BriefingQueryService.class);
        when(service.get(null, null, "request-transaction"))
                .thenThrow(new CannotCreateTransactionException("private-db-address-and-credentials"));
        var mvc = MockMvcBuilders.standaloneSetup(new BriefingController(service))
                .setControllerAdvice(new BriefingReadExceptionHandler(), new GlobalExceptionHandler())
                .addFilters(new RequestIdFilter()).build();
        mvc.perform(get("/api/v1/briefings").header("X-Request-ID", "request-transaction"))
                .andExpect(status().isServiceUnavailable())
                .andExpect(header().string("X-Request-ID", "request-transaction"))
                .andExpect(jsonPath("$.error.code").value("SOURCE_UNAVAILABLE"))
                .andExpect(jsonPath("$.error.requestId").value("request-transaction"))
                .andExpect(content().string(org.hamcrest.Matchers.not(org.hamcrest.Matchers.containsString("private-db"))));
    }
}
