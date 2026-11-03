package com.zoop.common.request;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertThrows;

import java.util.concurrent.atomic.AtomicInteger;
import jakarta.servlet.ServletException;
import org.junit.jupiter.api.Test;
import org.springframework.mock.web.MockHttpServletRequest;
import org.springframework.mock.web.MockHttpServletResponse;

class ReadScopeFilterTest {
    private final ReadScopeFilter filter = new ReadScopeFilter();

    /** Computations made by two reads of the same key inside one request. */
    private int computations(String method) throws Exception {
        AtomicInteger calls = new AtomicInteger();
        filter.doFilter(new MockHttpServletRequest(method, "/api/v1/graph"), new MockHttpServletResponse(),
                (request, response) -> {
                    ReadScope.memo("k", calls::incrementAndGet);
                    ReadScope.memo("k", calls::incrementAndGet);
                });
        return calls.get();
    }

    @Test
    void getAndHeadShareOneScopeAndWritesComputeEveryRead() throws Exception {
        assertEquals(1, computations("GET"));
        assertEquals(1, computations("HEAD"));
        for (String write : new String[] {"POST", "PUT", "PATCH", "DELETE"})
            assertEquals(2, computations(write), write + " must re-verify every read");
    }

    @Test
    void theScopeClosesAfterTheRequestEvenWhenItFails() {
        assertThrows(ServletException.class, () -> filter.doFilter(new MockHttpServletRequest("GET", "/api/v1/graph"),
                new MockHttpServletResponse(), (request, response) -> {
                    ReadScope.memo("k", () -> "kept");
                    throw new ServletException("failed");
                }));
        AtomicInteger calls = new AtomicInteger();
        ReadScope.memo("k", calls::incrementAndGet);
        ReadScope.memo("k", calls::incrementAndGet);
        assertEquals(2, calls.get(), "no scope is left open on the thread");
    }
}
