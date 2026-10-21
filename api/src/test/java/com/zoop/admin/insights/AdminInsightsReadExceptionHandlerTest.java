package com.zoop.admin.insights;

import com.zoop.common.request.RequestIdFilter;
import org.junit.jupiter.api.Test;
import org.springframework.dao.DataAccessResourceFailureException;
import org.springframework.http.HttpStatus;
import org.springframework.mock.web.MockHttpServletRequest;

import static org.junit.jupiter.api.Assertions.assertEquals;

class AdminInsightsReadExceptionHandlerTest {
    @Test
    void transientDatabaseResourceFailureIsRetryableUnavailable() {
        var request = new MockHttpServletRequest();
        request.setAttribute(RequestIdFilter.ATTRIBUTE, "insights-read-request");

        var response = new AdminInsightsReadExceptionHandler().unavailable(
                new DataAccessResourceFailureException("database unavailable"), request);

        assertEquals(HttpStatus.SERVICE_UNAVAILABLE, response.getStatusCode());
        assertEquals("SOURCE_UNAVAILABLE", response.getBody().error().code());
        assertEquals("insights-read-request", response.getBody().error().requestId());
        assertEquals(true, response.getBody().error().retryable());
    }
}
