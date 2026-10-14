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
import org.springframework.stereotype.Service;
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

    public CompanySearchPage search(String q, String cursor, Integer limit, String graphVersion, Instant asOf) {
        long startedAt = System.nanoTime();
        log.debug("Company search started: limit={}, cursorPresent={}", limit, cursor != null);
        if (limit != null && limit < 1) {
            throw new IllegalArgumentException("limit must be positive");
        }
        String normalizedQuery = repository.normalize(q == null ? "" : q);
        Position after = cursor == null
                ? null : decode(cursor, normalizedQuery, limit, graphVersion, asOf);
        CompanySearchPosition sortPosition = after == null ? null
                : new CompanySearchPosition(after.rank(), after.name(), after.id());
        List<CompanySearchRow> rows = repository.search(normalizedQuery, sortPosition,
                limit == null ? null : (long) limit + 1);
        CompanySearchPage page;
        if (limit == null || rows.size() <= limit) {
            page = new CompanySearchPage(rows, null);
        } else {
            List<CompanySearchRow> items = rows.subList(0, limit);
            CompanySearchRow last = items.get(items.size() - 1);
            String next = encode(new Position(normalizedQuery, graphVersion, asOf, limit,
                    last.matchRank(), last.name(), last.id()));
            page = new CompanySearchPage(items, next);
        }
        log.debug("Company search completed: resultCount={}, hasNext={}, elapsedMs={}",
                page.items().size(), page.nextCursor() != null,
                TimeUnit.NANOSECONDS.toMillis(System.nanoTime() - startedAt));
        return page;
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
            Position position = objectMapper.readValue(
                    Base64.getUrlDecoder().decode(cursor), Position.class);
            if (!position.query().equals(query)
                    || !java.util.Objects.equals(position.limit(), limit)
                    || !java.util.Objects.equals(position.graphVersion(), graphVersion)
                    || !java.util.Objects.equals(position.asOf(), asOf)
                    || position.rank() < 0 || position.rank() > 2
                    || position.name() == null || position.id() == null) {
                throw new IllegalArgumentException("Cursor does not match this company search");
            }
            return position;
        } catch (IllegalArgumentException exception) {
            throw exception;
        } catch (Exception exception) {
            throw new IllegalArgumentException("Invalid company search cursor", exception);
        }
    }

    public record Position(String query, String graphVersion, Instant asOf,
                           Integer limit, int rank, String name, String id) {
    }
}
