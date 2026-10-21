package com.zoop.admin.insights;

import java.sql.Timestamp;
import java.time.Clock;
import java.time.Instant;
import java.time.LocalDate;
import java.time.ZoneId;
import java.time.temporal.ChronoUnit;
import java.util.ArrayList;
import java.util.Base64;
import java.util.HashMap;
import java.util.List;
import java.util.Map;
import java.util.Set;
import java.util.UUID;

import com.zoop.common.exception.CustomException;
import com.zoop.common.exception.ErrorCode;
import com.zoop.portfolio.service.MockPortfolioCatalog;
import org.springframework.jdbc.core.namedparam.MapSqlParameterSource;
import org.springframework.jdbc.core.namedparam.NamedParameterJdbcTemplate;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Isolation;
import org.springframework.transaction.annotation.Transactional;

@Service
public class AdminInsightsService {
    private static final ZoneId KST = ZoneId.of("Asia/Seoul");
    private static final int MIN_SAMPLE = 5;
    private final NamedParameterJdbcTemplate jdbc;
    private final Clock clock;
    private final MockPortfolioCatalog portfolios;

    public AdminInsightsService(NamedParameterJdbcTemplate jdbc, Clock clock, MockPortfolioCatalog portfolios) {
        this.jdbc = jdbc;
        this.clock = clock;
        this.portfolios = portfolios;
    }

    @Transactional(readOnly = true)
    public Overview overview(String requestId) {
        Instant asOf = clock.instant();
        Window window = window("7d", asOf);
        List<Metric> metrics = metrics(window, asOf);
        MemberCounts members = jdbc.queryForObject("""
                SELECT count(*) AS registered,
                       count(*) FILTER (WHERE status='active') AS active,
                       count(*) FILTER (WHERE status='blocked') AS blocked
                FROM members WHERE created_at < :asOf
                """, params(window, asOf), (rs, n) -> new MemberCounts(rs.getLong("registered"),
                rs.getLong("active"), rs.getLong("blocked")));
        return new Overview("7d", asOf, MIN_SAMPLE, metrics,
                new Feedback(null, null, null, false, "unavailable", "not_integrated"), members);
    }

    @Transactional(readOnly = true)
    public Summary summary(String requestedWindow, String requestId) {
        Instant asOf = clock.instant();
        Window w = window(requestedWindow, asOf);
        var trend = new ArrayList<DailyActivity>();
        if (w.days() > 0) {
            for (int i = 0; i < w.days(); i++) {
                LocalDate date = w.startDate().plusDays(i);
                Instant start = date.atStartOfDay(KST).toInstant();
                Instant end = date.plusDays(1).atStartOfDay(KST).toInstant();
                var p = new MapSqlParameterSource().addValue("start", Timestamp.from(start))
                        .addValue("end", Timestamp.from(end.isAfter(asOf) ? asOf : end));
                trend.add(jdbc.queryForObject("""
                        SELECT count(DISTINCT principal_key) AS active,
                            count(*) FILTER (WHERE event_type='graph_node_select') AS nodes,
                            count(*) FILTER (WHERE event_type='graph_edge_select') AS edges,
                            count(*) FILTER (WHERE event_type='briefing_view') AS briefs,
                            count(*) FILTER (WHERE event_type='ai_question') AS ai
                        FROM telemetry_events WHERE occurred_at >= :start AND occurred_at < :end
                        """, p, (rs, n) -> new DailyActivity(date, rs.getLong("active"), rs.getLong("nodes"),
                        rs.getLong("edges"), rs.getLong("briefs"), rs.getLong("ai"))));
            }
        }
        var rounds = jdbc.query("""
                SELECT r.id, r.round_date, r.edition,
                    count(DISTINCT (e.principal_key, e.view_id)) FILTER (WHERE e.event_type='briefing_view') AS views,
                    count(DISTINCT e.principal_key) FILTER (WHERE e.event_type='briefing_view') AS viewers,
                    count(e.id) FILTER (WHERE e.event_type='briefing_issue_open') AS opens
                FROM briefing_rounds r LEFT JOIN telemetry_events e
                    ON coalesce(e.round_id,e.target_id)=r.id
                    AND (CAST(:start AS timestamptz) IS NULL OR e.occurred_at >= :start) AND e.occurred_at < :asOf
                WHERE r.round_date >= :startDate AND r.round_date <= :asOfDate
                GROUP BY r.id, r.round_date, r.edition ORDER BY r.round_date DESC, r.edition DESC
                """, params(w, asOf).addValue("startDate", w.startDate())
                        .addValue("asOfDate", asOf.atZone(KST).toLocalDate()), (rs, n) ->
                        new RoundStat(rs.getString("id"), rs.getObject("round_date", LocalDate.class),
                                rs.getString("edition"), rs.getLong("views"), rs.getLong("viewers"),
                                rs.getLong("opens"), null, null));
        return new Summary(w.name(), asOf, w.name().equals("all") ? null : w.startDate().toString(), MIN_SAMPLE,
                "선택 기간에 가입한 회원 계정이며 완료 여부는 asOf 시점의 현재 상태입니다.", metrics(w, asOf),
                List.copyOf(trend), rounds);
    }

    @Transactional(isolation = Isolation.REPEATABLE_READ)
    public CompanyRanking companies(String requestedWindow, String cursor, Integer requestedLimit, String requestId) {
        Instant now = clock.instant().truncatedTo(ChronoUnit.MICROS);
        int limit = requestedLimit == null ? 50 : requestedLimit;
        if (limit < 1 || limit > 100) throw invalid();
        if (cursor == null) {
            Window w = window(requestedWindow, now);
            String snapshotId = UUID.randomUUID().toString();
            var p = params(w, now);
            List<CompanyRow> ranked = jdbc.query("""
                SELECT c.id,c.name,c.ticker,
                    (SELECT count(DISTINCT member_id) FROM member_watchlist WHERE company_id=c.id) AS watches,
                    count(e.id) FILTER (WHERE e.event_type='graph_node_select') AS nodes,
                    count(e.id) FILTER (WHERE e.event_type='ai_question') AS ai
                FROM companies c LEFT JOIN telemetry_events e ON e.target_id=c.id
                    AND (CAST(:start AS timestamptz) IS NULL OR e.occurred_at >= :start) AND e.occurred_at < :asOf
                GROUP BY c.id,c.name,c.ticker ORDER BY nodes DESC, c.id
                """, p, (rs,n) -> new CompanyRow(rs.getString("id"), rs.getString("name"), rs.getString("ticker"),
                        rs.getLong("watches"), 0L, rs.getLong("nodes"), null, rs.getLong("ai")));
            Map<String, Long> holdings = holdingMembersByCompany(ranked.stream()
                    .map(CompanyRow::companyId).collect(java.util.stream.Collectors.toSet()));
            List<CompanyRow> snapshotRows = ranked.stream().map(row -> new CompanyRow(row.companyId(), row.name(),
                    row.ticker(), row.watchlistMembers(), holdings.getOrDefault(row.companyId(), 0L),
                    row.nodeViews(), null, row.aiQuestions())).toList();
            jdbc.update("DELETE FROM admin_insights_company_snapshots WHERE expires_at <= :now",
                    new MapSqlParameterSource("now", Timestamp.from(now)));
            jdbc.update("""
                    INSERT INTO admin_insights_company_snapshots
                        (id,window_name,page_size,as_of,total_companies,created_at,expires_at)
                    VALUES (:id,:window,:pageSize,:asOf,:total,:now,:expiresAt)
                    """, new MapSqlParameterSource().addValue("id", snapshotId).addValue("window", w.name())
                    .addValue("pageSize", limit).addValue("asOf", Timestamp.from(now))
                    .addValue("total", snapshotRows.size()).addValue("now", Timestamp.from(now))
                    .addValue("expiresAt", Timestamp.from(now.plus(30, ChronoUnit.MINUTES))));
            var rowParams = new ArrayList<MapSqlParameterSource>();
            for (int ordinal = 0; ordinal < snapshotRows.size(); ordinal++) {
                CompanyRow row = snapshotRows.get(ordinal);
                rowParams.add(new MapSqlParameterSource().addValue("snapshot", snapshotId)
                        .addValue("ordinal", ordinal).addValue("company", row.companyId())
                        .addValue("name", row.name()).addValue("ticker", row.ticker())
                        .addValue("watches", row.watchlistMembers()).addValue("holdings", row.holdingMembers())
                        .addValue("nodes", row.nodeViews()).addValue("ai", row.aiQuestions()));
            }
            if (!rowParams.isEmpty()) jdbc.batchUpdate("""
                    INSERT INTO admin_insights_company_snapshot_rows
                        (snapshot_id,ordinal,company_id,name,ticker,watchlist_members,holding_members,node_views,ai_questions)
                    VALUES (:snapshot,:ordinal,:company,:name,:ticker,:watches,:holdings,:nodes,:ai)
                    """, rowParams.toArray(MapSqlParameterSource[]::new));
            return companySnapshotPage(snapshotId, 0, requestedWindow, limit);
        }

        Cursor position = decodeCursor(cursor, requestedWindow, limit);
        return companySnapshotPage(position.snapshotId(), position.offset(), requestedWindow, limit);
    }

    private CompanyRanking companySnapshotPage(String snapshotId, int offset, String requestedWindow, int limit) {
        Instant now = clock.instant();
        List<SnapshotMetadata> snapshots = jdbc.query("""
                SELECT window_name,page_size,as_of,total_companies FROM admin_insights_company_snapshots
                WHERE id=:id AND expires_at>:now
                """, new MapSqlParameterSource().addValue("id", snapshotId).addValue("now", Timestamp.from(now)),
                (rs, n) -> new SnapshotMetadata(rs.getString("window_name"), rs.getInt("page_size"),
                        rs.getTimestamp("as_of").toInstant(), rs.getLong("total_companies")));
        if (snapshots.isEmpty()) throw new CustomException(ErrorCode.INVALID_CURSOR);
        SnapshotMetadata snapshot = snapshots.getFirst();
        if (!snapshot.window().equals(requestedWindow) || snapshot.pageSize() != limit
                || offset < 0 || (offset != 0 && (offset >= snapshot.totalCompanies() || offset % limit != 0))) {
            throw new CustomException(ErrorCode.INVALID_CURSOR);
        }
        var rows = jdbc.query("""
                SELECT company_id,name,ticker,watchlist_members,holding_members,node_views,ai_questions
                FROM admin_insights_company_snapshot_rows
                WHERE snapshot_id=:snapshot AND ordinal>=:offset
                ORDER BY ordinal LIMIT :limit
                """, new MapSqlParameterSource().addValue("snapshot", snapshotId).addValue("offset", offset)
                .addValue("limit", limit + 1), (rs, n) -> new CompanyRow(rs.getString("company_id"),
                rs.getString("name"), rs.getString("ticker"), rs.getLong("watchlist_members"),
                rs.getLong("holding_members"), rs.getLong("node_views"), null, rs.getLong("ai_questions")));
        boolean more = rows.size() > limit;
        List<CompanyRow> items = more ? rows.subList(0, limit) : rows;
        return new CompanyRanking(snapshot.window(), snapshot.asOf(), snapshot.totalCompanies(), items,
                "기업 순위와 집계는 첫 페이지 조회 시점에 고정됩니다. Mock 포트폴리오 연결 기준의 현재 보유 회원 수입니다.",
                more ? encodeCursor(snapshotId, snapshot.window(), limit, offset + limit) : null);
    }

    @Transactional(readOnly = true)
    public CompanyDetail company(String companyId, String requestedWindow, String requestId) {
        Instant asOf = clock.instant();
        Window w = window(requestedWindow, asOf);
        var company = jdbc.query("SELECT id,name,ticker FROM companies WHERE id=:id",
                new MapSqlParameterSource("id", companyId), (rs,n) -> new CompanyRow(rs.getString("id"),
                        rs.getString("name"), rs.getString("ticker"), 0L, 0L, 0L, 0L, 0L)).stream().findFirst()
                .orElseThrow(() -> new CustomException(ErrorCode.RESOURCE_NOT_FOUND));
        var p = params(w, asOf).addValue("company", companyId);
        var series = new ArrayList<CompanySeries>();
        if (w.days() > 0) {
            for (int i=0; i<w.days(); i++) {
                LocalDate date = w.startDate().plusDays(i);
                Instant start = date.atStartOfDay(KST).toInstant();
                Instant end = date.plusDays(1).atStartOfDay(KST).toInstant();
                var day = new MapSqlParameterSource().addValue("company", companyId)
                        .addValue("start", Timestamp.from(start)).addValue("end", Timestamp.from(end.isAfter(asOf) ? asOf : end));
                series.add(jdbc.queryForObject("""
                        SELECT count(*) FILTER (WHERE event_type='graph_node_select') AS nodes,
                               count(*) FILTER (WHERE event_type='graph_edge_select') AS edges,
                               count(*) FILTER (WHERE event_type='ai_question') AS ai
                        FROM telemetry_events WHERE target_id=:company AND occurred_at>=:start AND occurred_at<:end
                        """, day, (rs,n) -> new CompanySeries(date, rs.getLong("nodes"),null,null,rs.getLong("ai"))));
            }
        }
        var counts = jdbc.queryForObject("""
                SELECT (SELECT count(DISTINCT member_id) FROM member_watchlist WHERE company_id=:company) watches,
                       count(DISTINCT e.principal_key) AS viewers,
                       count(*) FILTER (WHERE e.event_type='graph_node_select') AS nodes,
                       count(*) FILTER (WHERE e.event_type='graph_edge_select') AS edges,
                       count(*) FILTER (WHERE e.event_type='ai_question') AS ai
                FROM telemetry_events e WHERE e.target_id=:company
                    AND (CAST(:start AS timestamptz) IS NULL OR e.occurred_at>=:start) AND e.occurred_at<:asOf
                """, p, (rs,n) -> new CompanyCounts(rs.getLong("watches"), 0L,
                        rs.getLong("viewers"),rs.getLong("nodes"),rs.getLong("edges"),rs.getLong("ai")));
        return new CompanyDetail(w.name(), asOf, company.companyId(), company.name(), company.ticker(), true,
                counts.watches(), holdingMembers(companyId), counts.nodes(), null, null, counts.ai(), counts.viewers(),
                MIN_SAMPLE, List.copyOf(series), "관심·보유 회원 수는 현재 스냅샷이며 기업별 사건 열기는 단일 기업 연결 원천이 없어 제공하지 않습니다.");
    }

    private List<Metric> metrics(Window w, Instant asOf) {
        var p = params(w, asOf);
        var values = jdbc.queryForObject("""
                WITH events AS (
                    SELECT * FROM telemetry_events WHERE (CAST(:start AS timestamptz) IS NULL OR occurred_at>=:start) AND occurred_at<:asOf
                ), views AS (SELECT * FROM events WHERE event_type='screen_view')
                SELECT (SELECT count(DISTINCT principal_key) FROM events) active,
                  count(DISTINCT (v.principal_key,v.view_id)) FILTER (WHERE v.screen='main') main_views,
                  count(DISTINCT (v.principal_key,v.view_id)) FILTER (WHERE v.screen='main' AND EXISTS
                    (SELECT 1 FROM events e WHERE e.principal_key=v.principal_key AND e.view_id=v.view_id
                     AND e.event_type='graph_node_select')) nodes,
                  count(DISTINCT (v.principal_key,v.view_id)) FILTER (WHERE v.screen='main' AND EXISTS
                    (SELECT 1 FROM events e WHERE e.principal_key=v.principal_key AND e.view_id=v.view_id
                     AND e.event_type='graph_edge_select')) edges,
                  count(DISTINCT (v.principal_key,v.view_id)) FILTER (WHERE v.screen='briefing') briefing_views,
                  count(DISTINCT (v.principal_key,v.view_id)) FILTER (WHERE v.screen='briefing' AND EXISTS
                    (SELECT 1 FROM events e WHERE e.principal_key=v.principal_key AND e.view_id=v.view_id
                     AND e.event_type='briefing_view')) briefing_detail_views,
                  (SELECT count(*) FROM events WHERE event_type='briefing_issue_open') issue_opens,
                  count(DISTINCT (v.principal_key,v.view_id)) FILTER (WHERE v.screen='ai') ai_views,
                  count(DISTINCT (v.principal_key,v.view_id)) FILTER (WHERE v.screen='ai' AND EXISTS
                    (SELECT 1 FROM events e WHERE e.principal_key=v.principal_key AND e.view_id=v.view_id
                     AND e.event_type='ai_question')) ai_question_views,
                  (SELECT count(*) FROM events WHERE event_type='ai_question') ai_question_events
                FROM views v
                """, p, (rs,n) -> new EventCounts(rs.getLong("active"),rs.getLong("main_views"),rs.getLong("nodes"),
                        rs.getLong("edges"),rs.getLong("briefing_views"),rs.getLong("briefing_detail_views"),
                        rs.getLong("issue_opens"),rs.getLong("ai_views"),rs.getLong("ai_question_views"),
                        rs.getLong("ai_question_events")));
        var members = jdbc.queryForObject("""
                SELECT count(*) total, count(*) FILTER (WHERE completed) completed FROM members
                WHERE (CAST(:start AS timestamptz) IS NULL OR created_at>=:start) AND created_at<:asOf
                """, p, (rs,n) -> new long[]{rs.getLong("total"),rs.getLong("completed")});
        return List.of(metric("activeUsers","usage","활성 사용자","count","principal","선택 기간에 이벤트를 1회 이상 발생시킨 회원·게스트 수",values.active(),null,null,null,false),
                metric("onboarding","usage","온보딩 완료율","ratio","회원","선택 기간 가입 회원 중 asOf 시점 완료 비율",null,members[1],members[0],members[0]<MIN_SAMPLE?null:ratio(members[1],members[0]),members[0]<MIN_SAMPLE),
                metric("nodeCtr","usage","노드 클릭률","ratio","화면 조회","main 화면 조회 중 노드 선택이 있는 비율",null,values.nodes(),values.mainViews(),values.mainViews()<MIN_SAMPLE?null:ratio(values.nodes(),values.mainViews()),values.mainViews()<MIN_SAMPLE),
                metric("edgeCtr","usage","간선 클릭률","ratio","화면 조회","main 화면 조회 중 간선 선택이 있는 비율",null,values.edges(),values.mainViews(),values.mainViews()<MIN_SAMPLE?null:ratio(values.edges(),values.mainViews()),values.mainViews()<MIN_SAMPLE),
                metric("briefingRate","interest","브리핑 조회율","ratio","화면 조회","브리핑 화면 조회 중 상세 조회가 있는 비율",null,values.briefingDetailViews(),values.briefingViews(),values.briefingViews()<MIN_SAMPLE?null:ratio(values.briefingDetailViews(),values.briefingViews()),values.briefingViews()<MIN_SAMPLE),
                metric("briefingIssueOpens","interest","브리핑 사건 열기","count","건","접수된 사건 열기 이벤트 수",values.issueOpens(),null,null,null,false),
                metric("aiQuestions","ai","AI 질문 제출","count","건","질문 본문 없이 수집된 제출 이벤트 수",values.aiQuestionEvents(),null,null,null,false),
                metric("aiQuestionRate","ai","AI 질문 이용률","ratio","화면 조회","AI 화면 조회 중 질문 제출이 있는 비율",null,values.aiQuestionViews(),values.aiViews(),values.aiViews()<MIN_SAMPLE?null:ratio(values.aiQuestionViews(),values.aiViews()),values.aiViews()<MIN_SAMPLE));
    }

    private static Metric metric(String key,String group,String label,String kind,String unit,String definition,Long count,
            Long numerator,Long denominator,Double rate,boolean hidden) {
        return new Metric(key,group,label,kind,unit,definition,"available",null,count,numerator,denominator,rate,hidden);
    }
    private static double ratio(long n,long d) { return d == 0 ? 0d : (double)n/d; }
    private Window window(String name, Instant asOf) {
        if (!List.of("7d","30d","all").contains(name)) throw invalid();
        int days = "7d".equals(name) ? 7 : "30d".equals(name) ? 30 : 0;
        LocalDate today = asOf.atZone(KST).toLocalDate();
        LocalDate startDate;
        if (days == 0) {
            LocalDate earliest = jdbc.queryForObject("""
                    SELECT min(source_date) FROM (
                        SELECT min((occurred_at AT TIME ZONE 'Asia/Seoul')::date) source_date FROM telemetry_events
                        UNION ALL SELECT min((created_at AT TIME ZONE 'Asia/Seoul')::date) FROM members
                    ) sources
                    """, new MapSqlParameterSource(), LocalDate.class);
            startDate = earliest == null ? today : earliest;
            days = Math.toIntExact(Math.max(1, java.time.temporal.ChronoUnit.DAYS.between(startDate, today) + 1));
        } else {
            startDate = today.minusDays(days - 1L);
        }
        Instant start = "all".equals(name) ? null : startDate.atStartOfDay(KST).toInstant();
        return new Window(name,start,startDate,days);
    }
    private static MapSqlParameterSource params(Window w, Instant asOf) {
        return new MapSqlParameterSource().addValue("start", w.start()==null?null:Timestamp.from(w.start()))
                .addValue("asOf",Timestamp.from(asOf));
    }
    private static Cursor decodeCursor(String cursor,String window,int limit) {
        if (cursor==null) return null;
        try { String[] p=new String(Base64.getUrlDecoder().decode(cursor), java.nio.charset.StandardCharsets.UTF_8)
                    .split("\\|",-1);
            if(p.length!=4||!p[1].equals(window)||Integer.parseInt(p[2])!=limit)throw new IllegalArgumentException();
            UUID.fromString(p[0]);
            int offset=Integer.parseInt(p[3]); if(offset<1||offset>1000000)throw new IllegalArgumentException();
            return new Cursor(p[0], offset);
        } catch(Exception e) { throw new CustomException(ErrorCode.INVALID_CURSOR,e); }
    }
    private static String encodeCursor(String snapshotId, String window,int limit,int offset) {
        return Base64.getUrlEncoder().withoutPadding().encodeToString(
                (snapshotId+"|"+window+"|"+limit+"|"+offset).getBytes(java.nio.charset.StandardCharsets.UTF_8));
    }
    private static CustomException invalid(){return new CustomException(ErrorCode.INVALID_REQUEST);}
    private long holdingMembers(String companyId) {
        return holdingMembersByCompany(Set.of(companyId)).getOrDefault(companyId, 0L);
    }

    private Map<String, Long> holdingMembersByCompany(Set<String> companyIds) {
        if (companyIds.isEmpty()) return Map.of();
        var portfolioIds = portfolios.all().stream().filter(portfolio -> portfolio.holdings().stream()
                .anyMatch(holding -> companyIds.contains(holding.companyId())))
                .map(com.zoop.portfolio.model.MockPortfolio::id).toList();
        if (portfolioIds.isEmpty()) return Map.of();
        var counts = new HashMap<String, Long>();
        jdbc.query("""
                SELECT company_id,count(DISTINCT member_id) AS members
                FROM member_portfolio_connections WHERE mock_portfolio_id IN (:portfolios)
                AND company_id IN (:companies) GROUP BY company_id
                """, new MapSqlParameterSource().addValue("portfolios", portfolioIds)
                .addValue("companies", companyIds), rs -> {
                    counts.put(rs.getString("company_id"), rs.getLong("members"));
                });
        return counts;
    }

    private record Window(String name,Instant start,LocalDate startDate,int days) { }
    private record Cursor(String snapshotId,int offset) { }
    private record SnapshotMetadata(String window,int pageSize,Instant asOf,long totalCompanies) { }
    private record EventCounts(long active,long mainViews,long nodes,long edges,long briefingViews,long briefingDetailViews,
            long issueOpens,long aiViews,long aiQuestionViews,long aiQuestionEvents) { }
    private record CompanyCounts(long watches,long holdings,long viewers,long nodes,long edges,long ai) { }
    public record Overview(String window,Instant asOf,int minSample,List<Metric> metrics,Feedback feedback,MemberCounts members) { }
    public record Summary(String window,Instant asOf,String since,int minSample,String membersScope,List<Metric> metrics,List<DailyActivity> trend,List<RoundStat> rounds) { }
    public record Metric(String key,String group,String label,String kind,String unit,String definition,String availability,String unavailableReason,Long count,Long numerator,Long denominator,Double rate,boolean sampleHidden) { }
    public record Feedback(Long up,Long down,Double rate,boolean sampleHidden,String availability,String unavailableReason) { }
    public record MemberCounts(long registered,long active,long blocked) { }
    public record DailyActivity(LocalDate date,long activeUsers,long nodeSelections,long edgeSelections,long briefingViews,Long aiQuestions) { }
    public record RoundStat(String roundId,LocalDate date,String edition,long views,long viewers,long issueOpens,Long likes,Long dislikes) { }
    public record CompanyRow(String companyId,String name,String ticker,long watchlistMembers,long holdingMembers,long nodeViews,Long edgeSelections,Long aiQuestions) { }
    public record CompanyRanking(String window,Instant asOf,long totalCompanies,List<CompanyRow> items,String holdingsNote,String nextCursor) { }
    public record CompanySeries(LocalDate date,long nodeViews,Long edgeSelections,Long issueSelections,Long aiQuestions) { }
    public record CompanyDetail(String window,Instant asOf,String companyId,String name,String ticker,boolean inCatalog,long watchlistMembers,long holdingMembers,long nodeViews,Long edgeSelections,Long issueSelections,Long aiQuestions,long viewers,int minSample,List<CompanySeries> series,String note) { }
}
