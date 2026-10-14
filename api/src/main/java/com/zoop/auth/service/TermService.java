package com.zoop.auth.service;

import java.time.Clock;
import java.time.Instant;
import java.util.List;

import com.zoop.auth.dto.TermOut;
import com.zoop.auth.dto.TermsResponse;
import com.zoop.auth.repository.TermRepository;
import com.zoop.auth.repository.TermRow;
import com.zoop.common.exception.CustomException;
import com.zoop.common.exception.ErrorCode;
import org.springframework.dao.DataAccessException;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

@Service
public class TermService {
    private final TermRepository repository;
    private final Clock clock;

    public TermService(TermRepository repository, Clock clock) {
        this.repository = repository;
        this.clock = clock;
    }

    @Transactional(readOnly = true)
    public TermsResponse list(String cursor, Integer requestedLimit) {
        if (requestedLimit != null && requestedLimit < 1) {
            throw new CustomException(ErrorCode.INVALID_REQUEST);
        }

        Instant now = clock.instant();
        Instant asOf = now;
        String afterId = "";
        Integer limit = requestedLimit;
        if (cursor != null) {
            var decoded = TermsCursor.decode(cursor, now);
            if (requestedLimit != null && requestedLimit != decoded.limit()) {
                throw new CustomException(ErrorCode.INVALID_CURSOR);
            }
            asOf = decoded.asOf();
            afterId = decoded.afterId();
            limit = decoded.limit();
        }

        List<TermRow> rows;
        try {
            rows = repository.listAt(asOf, afterId, limit == null ? null : (long) limit + 1);
        } catch (DataAccessException exception) {
            throw new CustomException(ErrorCode.SOURCE_UNAVAILABLE, exception);
        }
        boolean hasNext = limit != null && rows.size() > limit;
        List<TermRow> page = hasNext ? rows.subList(0, limit) : rows;
        List<TermOut> items = page.stream()
                .map(row -> new TermOut(row.title(), row.body(), row.version(), row.id(),
                        row.required(), row.body() != null && row.version() != null))
                .toList();
        String nextCursor = hasNext
                ? TermsCursor.encode(asOf, page.get(page.size() - 1).id(), limit)
                : null;
        return new TermsResponse(items, nextCursor);
    }
}
