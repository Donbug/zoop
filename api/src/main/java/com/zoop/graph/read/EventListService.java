package com.zoop.graph.read;

import com.zoop.common.exception.CustomException;
import com.zoop.common.exception.ErrorCode;
import com.zoop.graph.read.dto.EventListResponse;
import com.zoop.graph.read.dto.EventListResponse.EventSummary;
import com.zoop.graph.snapshot.PublicGraphSnapshot.Issue;
import java.nio.charset.StandardCharsets;
import java.time.Instant;
import java.time.LocalDate;
import java.time.OffsetDateTime;
import java.time.YearMonth;
import java.time.ZoneId;
import java.time.format.DateTimeParseException;
import java.util.ArrayList;
import java.util.Base64;
import java.util.Collection;
import java.util.Comparator;
import java.util.List;
import java.util.Objects;
import java.util.Set;
import java.util.TreeSet;
import org.springframework.jdbc.core.namedparam.MapSqlParameterSource;
import org.springframework.jdbc.core.namedparam.NamedParameterJdbcTemplate;
import org.springframework.stereotype.Service;
import tools.jackson.databind.ObjectMapper;

/**
 * {@code listEvents}: the events of one pinned public version, for one company at depth 1 or 2 (the same literal hops
 * as {@code getCompanyGraphAsOf}) or for the whole graph. With from/to, {@code items} keeps the events whose approved
 * time span overlaps [from, to) and {@code unknownTimeItems} the events without an approved time whose latest report
 * falls in the range; without from/to every event is in {@code items}. Pages are offsets over one immutable version.
 */
@Service
public class EventListService {
    private static final ZoneId KST = ZoneId.of("Asia/Seoul");
    private static final Set<String> DIRECT = Set.of("INVOLVES", "STRUCTURALLY_RELATED_TO");

    private final PublicGraphReader reader;
    private final NamedParameterJdbcTemplate jdbc;
    private final ObjectMapper mapper;

    public EventListService(PublicGraphReader reader, NamedParameterJdbcTemplate jdbc, ObjectMapper mapper) {
        this.reader = reader;
        this.jdbc = jdbc;
        this.mapper = mapper;
    }

    /** Opaque page position, bound to the query and to the version and asOf the first page pinned. */
    /**
     * asOf is the request's own value (null: no asOf filter, the mode every page keeps); pinnedAt is the time the first page
     * resolved, sent back as metadata.asOf on every page so a later page does not report a new request time.
     */
    record Cursor(String companyId, Integer depth, String from, String to, Integer limit, String versionId, String asOf,
            String pinnedAt, int offset) { }

    public EventListResponse list(String companyId, Integer depth, String from, String to, String cursor, Integer limit,
            String graphVersion, String asOf) {
        if (limit != null && limit < 1) throw invalid();
        // depth is 1 or 2 (contract enum) and applies to a company scope only; the whole-graph list ignores it.
        if (depth != null && depth != 1 && depth != 2) throw invalid();
        Integer hops = companyId == null ? null : depth == null ? 1 : depth;
        Instant start = from == null ? null : bound(from, false);
        Instant end = to == null ? null : bound(to, true);
        if (start != null && end != null && !start.isBefore(end)) throw invalid();
        Instant requestedAsOf = parseInstant(asOf);
        if (companyId != null) requireCatalog(companyId);

        Cursor after = cursor == null ? null : decode(cursor);
        if (after != null && (!Objects.equals(after.companyId(), companyId) || !Objects.equals(after.depth(), hops)
                || !Objects.equals(after.from(), from) || !Objects.equals(after.to(), to)
                || (limit != null && !Objects.equals(after.limit(), limit))
                || (graphVersion != null && !graphVersion.equals(after.versionId()))
                || !Objects.equals(after.asOf(), asOf))) {
            throw new CustomException(ErrorCode.INVALID_CURSOR);
        }
        PublicGraphReader.Pinned pinned = reader.read(null, after != null ? after.versionId() : graphVersion, requestedAsOf);
        DisplayGraph graph = pinned.graph();

        Collection<Issue> scope = companyId == null ? graph.issues.values() : companyIssues(graph, companyId, hops);
        boolean ranged = start != null || end != null;
        List<Issue> timed = new ArrayList<>();
        List<Issue> unknown = new ArrayList<>();
        for (Issue issue : scope) {
            if (!ranged) timed.add(issue);
            else if (issue.eventTime() == null) unknown.add(issue);
            else if (overlaps(issue, start, end)) timed.add(issue);
        }
        timed.sort(DisplayGraph.RECENT);
        List<Issue> reported = unknown.stream().filter(i -> reportedIn(i, start, end))
                .sorted(Comparator.comparing((Issue i) -> DisplayGraph.publishedAt(i.latestPublishedAt()), Comparator.reverseOrder())
                        .thenComparing(Issue::issueId))
                .toList();

        // One sequence, timed events then unknown-time ones, so limit and cursor cover both arrays to the end.
        int count = timed.size() + reported.size();
        int offset = after == null ? 0 : after.offset();
        if (offset > count) throw new CustomException(ErrorCode.INVALID_CURSOR);
        int pageLimit = limit != null ? limit : after != null ? after.limit() : count - offset;
        // long: a forged cursor's offset + limit must not overflow into a negative end.
        int pageEnd = (int) Math.min(count, (long) offset + pageLimit);
        List<Issue> items = timed.subList(Math.min(offset, timed.size()), Math.min(pageEnd, timed.size()));
        List<Issue> undated = reported.subList(Math.max(0, offset - timed.size()), Math.max(0, pageEnd - timed.size()));
        // Without an asOf every page keeps the no-asOf read of the pinned version, and reports the first page's time.
        String pinnedAt = after != null && asOf == null ? after.pinnedAt() : pinned.selected().asOf().toString();
        String next = pageEnd < count
                ? encode(new Cursor(companyId, hops, from, to, pageLimit, pinned.selected().version().id(), asOf,
                        pinnedAt, pageEnd))
                : null;

        var metadata = new EventListResponse.Metadata("public_graph_snapshot", pinnedAt,
                pinned.selected().version().id(), timed.size(), unknown.size(), latestEventTime(scope),
                latestReported(scope));
        return new EventListResponse(items.stream().map(i -> summary(graph, i, companyId)).toList(),
                undated.stream().map(i -> summary(graph, i, companyId)).toList(), metadata, next);
    }

    /**
     * The company's events within the same literal hops as getCompanyGraphAsOf (2 also reaches FOLLOWS neighbours). No node
     * cap: the graph's cap trims newest-first over all time, so it would silently drop the events of an older range.
     */
    static List<Issue> companyIssues(DisplayGraph graph, String companyId, int hops) {
        GraphSelection.Result ego = GraphSelection.select(graph, List.of(companyId), 2, Integer.MAX_VALUE);
        GraphSelection.Result near = GraphSelection.neighbourhood(graph, ego, companyId, hops);
        return near.nodes().entrySet().stream().filter(e -> e.getValue() == GraphSelection.Kind.ISSUE)
                .map(e -> graph.issues.get(e.getKey())).toList();
    }

    private static EventSummary summary(DisplayGraph graph, Issue issue, String companyId) {
        // Edges are keyed by (type, source, target), and derived edges are SHARES_ISSUE only, so a direct key lookup is exact.
        List<String> relationTypes = companyId == null ? List.of() : DIRECT.stream().sorted()
                .filter(type -> graph.edges.containsKey(DisplayGraph.edgeId(type, issue.issueId(), companyId))).toList();
        return new EventSummary(issue.label(), issue.issueId(), issue.action(), issue.target(), issue.eventTime(),
                issue.timePrecision(), issue.period(), issue.assertionStatus(),
                List.copyOf(new TreeSet<>(graph.issueCompanies.getOrDefault(issue.issueId(), Set.of()))), relationTypes,
                issue.articleIds().size(), instantOrNull(issue.latestPublishedAt()));
    }

    /**
     * The approved time as a span in KST: a year, month or day covers that whole period, an instant is that instant.
     * The event is in the range when the span overlaps [start, end); an open bound does not limit.
     */
    static boolean overlaps(Issue issue, Instant start, Instant end) {
        Instant from;
        Instant until;
        String t = issue.eventTime();
        switch (issue.timePrecision()) {
            case "year" -> {
                from = LocalDate.of(Integer.parseInt(t), 1, 1).atStartOfDay(KST).toInstant();
                until = LocalDate.of(Integer.parseInt(t) + 1, 1, 1).atStartOfDay(KST).toInstant();
            }
            case "month" -> {
                YearMonth month = YearMonth.parse(t);
                from = month.atDay(1).atStartOfDay(KST).toInstant();
                until = month.plusMonths(1).atDay(1).atStartOfDay(KST).toInstant();
            }
            case "day" -> {
                LocalDate day = LocalDate.parse(t);
                from = day.atStartOfDay(KST).toInstant();
                until = day.plusDays(1).atStartOfDay(KST).toInstant();
            }
            default -> {
                from = Instant.parse(t);
                until = from.plusNanos(1);
            }
        }
        return (end == null || from.isBefore(end)) && (start == null || until.isAfter(start));
    }

    /** reportedAt's KST date (a date-only publication is that date) within the KST dates of [start, end). */
    static boolean reportedIn(Issue issue, Instant start, Instant end) {
        String value = issue.latestPublishedAt();
        if (value == null) return false;
        LocalDate day = value.length() == 10 ? LocalDate.parse(value) : Instant.parse(value).atZone(KST).toLocalDate();
        return (start == null || !day.isBefore(start.atZone(KST).toLocalDate()))
                && (end == null || !day.isAfter(end.minusNanos(1).atZone(KST).toLocalDate()));
    }

    private static String latestEventTime(Collection<Issue> scope) {
        return scope.stream().filter(i -> i.eventTime() != null).sorted(DisplayGraph.RECENT)
                .map(Issue::eventTime).findFirst().orElse(null);
    }

    /** reportedAt is a date-time in the contract; a date-only publication is never given a time, so it is left out. */
    private static String latestReported(Collection<Issue> scope) {
        return scope.stream().map(i -> instantOrNull(i.latestPublishedAt())).filter(Objects::nonNull)
                .map(Instant::parse).max(Comparator.naturalOrder()).map(Instant::toString).orElse(null);
    }

    private static String instantOrNull(String value) {
        return value == null || value.length() == 10 ? null : value;
    }

    private void requireCatalog(String companyId) {
        Integer found = jdbc.queryForObject("SELECT count(*) FROM companies WHERE id = :id",
                new MapSqlParameterSource("id", companyId), Integer.class);
        if (found == null || found == 0) throw new CustomException(ErrorCode.RESOURCE_NOT_FOUND);
    }

    private String encode(Cursor cursor) {
        return Base64.getUrlEncoder().withoutPadding().encodeToString(mapper.writeValueAsBytes(cursor));
    }

    private Cursor decode(String cursor) {
        try {
            Cursor c = mapper.readValue(new String(Base64.getUrlDecoder().decode(cursor), StandardCharsets.UTF_8), Cursor.class);
            if (c.versionId() == null || c.pinnedAt() == null || c.limit() == null || c.limit() < 1 || c.offset() < 1) {
                throw new CustomException(ErrorCode.INVALID_CURSOR);
            }
            Instant.parse(c.pinnedAt()); // a cursor is client input: a pinnedAt that is no instant is a bad cursor
            return c;
        } catch (CustomException exception) {
            throw exception;
        } catch (RuntimeException exception) {
            throw new CustomException(ErrorCode.INVALID_CURSOR, exception);
        }
    }

    /**
     * A bare date is that whole KST day (to: up to the next day); a date-time must carry its offset. An exact to
     * includes that instant, as in getCompanyPrices: the chart sends its asOf as to, and an event at asOf is on the graph.
     */
    static Instant bound(String value, boolean end) {
        try {
            if (value.length() == 10) return LocalDate.parse(value).plusDays(end ? 1 : 0).atStartOfDay(KST).toInstant();
            Instant at = OffsetDateTime.parse(value).toInstant();
            return end ? at.plusNanos(1) : at;
        } catch (DateTimeParseException exception) {
            throw new CustomException(ErrorCode.INVALID_REQUEST, exception);
        }
    }

    private static Instant parseInstant(String value) {
        if (value == null || value.isBlank()) return null;
        try {
            return OffsetDateTime.parse(value).toInstant();
        } catch (DateTimeParseException exception) {
            throw new CustomException(ErrorCode.INVALID_REQUEST, exception);
        }
    }

    private static CustomException invalid() {
        return new CustomException(ErrorCode.INVALID_REQUEST);
    }
}
