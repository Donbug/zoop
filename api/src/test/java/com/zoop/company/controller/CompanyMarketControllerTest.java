package com.zoop.company.controller;

import com.zoop.common.exception.CustomException;
import com.zoop.common.exception.ErrorCode;
import com.zoop.company.repository.CompanySearchRepository;
import org.junit.jupiter.api.Test;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.verifyNoInteractions;
import static org.mockito.Mockito.when;

class CompanyMarketControllerTest {
    @Test
    void pricesRejectInputsTheContractDoesNotAllowBeforeAnyLookup() {
        var repository = mock(CompanySearchRepository.class);
        var controller = new CompanyMarketController(repository, null, null);
        String[][] bad = {
                {"1q", null, null, null}, // unknown period
                {"1m", "2026-10-15T09:00:00", null, null}, // date-time without offset
                {"1m", "2026-10-16", "2026-10-15", null}, // from after to
                {"1m", null, null, "2026-10-15T00:00:00Z"}, // asOf is not a price parameter
                {"1d", "2026-10-15", "2026-10-15", null}, // 1d is the server's exchange session, never a client from
                {"1w", "2026-10-07T00:00:00+09:00", "2026-10-15T00:00:00+09:00", null}, // eight days
                {"1m", "2026-08-15", "2026-10-15", null}, // two months
                {"1d", "2020-01-01T00:00:00Z", null, null}, // to omitted is now, so years of minute bars
        };
        for (String[] input : bad) {
            var error = assertThrows(CustomException.class,
                    () -> controller.prices("KRX:005930", input[0], input[1], input[2], input[3], null, null));
            assertEquals(ErrorCode.INVALID_REQUEST, error.getErrorCode(), String.join(",", java.util.Arrays.asList(input)));
        }
        verifyNoInteractions(repository);
    }

    @Test
    void exactlyOnePeriodIsAllowedAsTheChartSendsIt() {
        var repository = mock(CompanySearchRepository.class);
        when(repository.findProfile("KRX:005930")).thenReturn(java.util.Optional.empty());
        var controller = new CompanyMarketController(repository, null, null);
        String[][] ok = {
                {"1d", null, "2026-10-16T14:00:00+09:00"}, // the chart's asOf only
                {"1w", "2026-10-09T09:00:00Z", "2026-10-16T09:00:00Z"},
                {"1m", "2026-02-28T00:00:00+09:00", "2026-03-31T00:00:00+09:00"}, // month end clamps like the chart
                {"1y", "2025-10-16", "2026-10-15"},
        };
        for (String[] input : ok) {
            // Past the range check the lookup runs; an unknown company is 404, not 422.
            var error = assertThrows(CustomException.class,
                    () -> controller.prices("KRX:005930", input[0], input[1], input[2], null, null, null));
            assertEquals(ErrorCode.RESOURCE_NOT_FOUND, error.getErrorCode(), String.join(",", input));
        }
    }

    @Test
    void quoteRejectsUnsupportedAsOfInsteadOfSilentlyReturningLatestPrice() {
        var repository = mock(CompanySearchRepository.class);
        var controller = new CompanyMarketController(repository, null, null);

        var error = assertThrows(CustomException.class,
                () -> controller.quote("KRX:005930", "2026-10-15T00:00:00Z", null, null));

        assertEquals(ErrorCode.INVALID_REQUEST, error.getErrorCode());
        verifyNoInteractions(repository);
    }

    @Test
    void quoteRejectsUnsupportedGraphVersionInsteadOfSilentlyReturningLatestPrice() {
        var repository = mock(CompanySearchRepository.class);
        var controller = new CompanyMarketController(repository, null, null);

        var error = assertThrows(CustomException.class,
                () -> controller.quote("KRX:005930", null, "graph-v7", null));

        assertEquals(ErrorCode.INVALID_REQUEST, error.getErrorCode());
        verifyNoInteractions(repository);
    }

    @Test
    void metricsRejectsUnsupportedAsOfInsteadOfSilentlyReturningLatestValues() {
        var repository = mock(CompanySearchRepository.class);
        var controller = new CompanyMarketController(repository, null, null);

        var error = assertThrows(CustomException.class,
                () -> controller.metrics("KRX:005930", "2026-10-15T00:00:00Z", null, null));

        assertEquals(ErrorCode.INVALID_REQUEST, error.getErrorCode());
        verifyNoInteractions(repository);
    }

    @Test
    void metricsRejectsUnsupportedGraphVersionInsteadOfSilentlyReturningLatestValues() {
        var repository = mock(CompanySearchRepository.class);
        var controller = new CompanyMarketController(repository, null, null);

        var error = assertThrows(CustomException.class,
                () -> controller.metrics("KRX:005930", null, "graph-v7", null));

        assertEquals(ErrorCode.INVALID_REQUEST, error.getErrorCode());
        verifyNoInteractions(repository);
    }
}
