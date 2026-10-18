package com.zoop.company.controller;

import com.zoop.common.exception.CustomException;
import com.zoop.common.exception.ErrorCode;
import com.zoop.company.repository.CompanySearchRepository;
import org.junit.jupiter.api.Test;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.verifyNoInteractions;

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
        };
        for (String[] input : bad) {
            var error = assertThrows(CustomException.class,
                    () -> controller.prices("KRX:005930", input[0], input[1], input[2], input[3], null, null));
            assertEquals(ErrorCode.INVALID_REQUEST, error.getErrorCode(), String.join(",", java.util.Arrays.asList(input)));
        }
        verifyNoInteractions(repository);
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
