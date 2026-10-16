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
