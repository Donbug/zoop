package com.zoop.company.service;

import java.time.Instant;
import java.util.Base64;
import java.util.List;
import java.util.concurrent.TimeUnit;

import tools.jackson.core.JacksonException;
import tools.jackson.databind.ObjectMapper;
import com.zoop.company.repository.CompanySearchPage;
import com.zoop.company.repository.CompanySearchPosition;
import com.zoop.company.repository.CompanySearchRepository;
import com.zoop.company.repository.CompanySearchRow;
import com.zoop.common.exception.CustomException;
import com.zoop.common.exception.ErrorCode;
import org.springframework.dao.DataAccessException;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Isolation;
import org.springframework.transaction.annotation.Propagation;
import org.springframework.transaction.annotation.Transactional;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

@Service
public class CompanySearchService {
    private static final Logger log = LoggerFactory.getLogger(CompanySearchService.class);
    private final CompanySearchRepository repository;
    private final ObjectMapper objectMapper;

    public CompanySearchService(CompanySearchRepository repository, ObjectMapper objectMapper) {
        this.repository = repository;
        this.objectMapper = objectMapper;
    }

    @Transactional(readOnly = true, isolation = Isolation.REPEATABLE_READ, propagation = Propagation.REQUIRES_NEW)
    public CompanySearchPage search(String q, String cursor, Integer limit, String graphVersion, Instant asOf) {
        long startedAt = System.nanoTime();
        log.debug("Company search started: limit={}, cursorPresent={}", limit, cursor != null);
        if (limit != null && limit < 1) {
            throw new CustomException(ErrorCode.INVALID_REQUEST);
        }
        try {
            repository.lockCatalogForSnapshot();
            long catalogRevision = repository.catalogRevision();
            String normalizedQuery = repository.normalize(q == null ? "" : q);
            Position after = cursor == null
                    ? null : decode(cursor, normalizedQuery, limit, graphVersion, asOf);
            if (after != null && !Long.valueOf(catalogRevision).equals(after.catalogRevision())) {
                throw new CustomException(ErrorCode.INVALID_CURSOR);
            }
            int pageLimit = limit != null ? limit : after == null ? 0 : after.limit();
            String pageGraphVersion = after != null && graphVersion == null ? after.graphVersion() : graphVersion;
            Instant pageAsOf = after != null && asOf == null ? after.asOf() : asOf;
            CompanySearchPosition sortPosition = after == null ? null
                    : new CompanySearchPosition(after.rank(), after.name(), after.id());
            List<CompanySearchRow> rows = repository.search(normalizedQuery, sortPosition,
                    pageLimit == 0 ? null : (long) pageLimit + 1);
            CompanySearchPage page;
            if (pageLimit == 0 || rows.size() <= pageLimit) {
                page = new CompanySearchPage(rows, null, pageGraphVersion, pageAsOf);
            } else {
                List<CompanySearchRow> items = rows.subList(0, pageLimit);
                CompanySearchRow last = items.get(items.size() - 1);
                String next = encode(new Position(normalizedQuery, pageGraphVersion, pageAsOf, pageLimit,
                        last.matchRank(), last.name(), last.id(), catalogRevision));
                page = new CompanySearchPage(items, next, pageGraphVersion, pageAsOf);
            }
            log.debug("Company search completed: resultCount={}, hasNext={}, elapsedMs={}",
                    page.items().size(), page.nextCursor() != null,
                    TimeUnit.NANOSECONDS.toMillis(System.nanoTime() - startedAt));
            return page;
        } catch (DataAccessException exception) {
            throw new CustomException(ErrorCode.SOURCE_UNAVAILABLE, exception);
        }
    }

    public CompanySearchPage pinGraphSnapshot(CompanySearchPage page, String graphVersion, Instant asOf) {
        String nextCursor = page.nextCursor();
        if (nextCursor != null) {
            Position position = readPosition(nextCursor);
            nextCursor = encode(new Position(position.query(), graphVersion, asOf, position.limit(),
                    position.rank(), position.name(), position.id(), position.catalogRevision()));
        }
        return new CompanySearchPage(page.items(), nextCursor, graphVersion, asOf);
    }

    private String encode(Position position) {
        try {
            return Base64.getUrlEncoder().withoutPadding().encodeToString(
                    objectMapper.writeValueAsBytes(position));
        } catch (JacksonException exception) {
            throw new IllegalStateException("Unable to encode company search cursor", exception);
        }
    }

    private Position decode(String cursor, String query, Integer limit, String graphVersion, Instant asOf) {
        try {
            Position position = readPosition(cursor);
            if (!position.query().equals(query)
                    || (limit != null && !java.util.Objects.equals(position.limit(), limit))
                    || (graphVersion != null && !java.util.Objects.equals(position.graphVersion(), graphVersion))
                    || (asOf != null && !java.util.Objects.equals(position.asOf(), asOf))
                    || position.rank() < 0 || position.rank() > 2
                    || position.name() == null || position.id() == null
                    || position.limit() == null || position.limit() < 1 || position.catalogRevision() == null) {
                throw new CustomException(ErrorCode.INVALID_CURSOR);
            }
            return position;
        } catch (CustomException exception) {
            throw exception;
        } catch (IllegalArgumentException exception) {
            throw new CustomException(ErrorCode.INVALID_CURSOR, exception);
        } catch (Exception exception) {
            throw new CustomException(ErrorCode.INVALID_CURSOR, exception);
        }
    }

    private Position readPosition(String cursor) {
        try {
            return objectMapper.readValue(Base64.getUrlDecoder().decode(cursor), Position.class);
        } catch (Exception exception) {
            throw new CustomException(ErrorCode.INVALID_CURSOR, exception);
        }
    }

    public record Position(String query, String graphVersion, Instant asOf,
                           Integer limit, int rank, String name, String id, Long catalogRevision) {
    }
}
