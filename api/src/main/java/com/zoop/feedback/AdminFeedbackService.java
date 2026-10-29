package com.zoop.feedback;

import com.zoop.auth.service.CsrfKeyRing;
import com.zoop.common.exception.CustomException;
import com.zoop.common.exception.ErrorCode;
import com.zoop.common.json.Canonical;
import java.sql.Timestamp;
import java.time.*;
import java.util.*;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Isolation;
import org.springframework.transaction.annotation.Transactional;
import tools.jackson.databind.ObjectMapper;
import tools.jackson.databind.node.ObjectNode;

@Service
@Transactional(readOnly = true, isolation = Isolation.REPEATABLE_READ)
public class AdminFeedbackService {
  private static final ZoneId KST = ZoneId.of("Asia/Seoul");
  private static final int MIN_SAMPLE = 5;
  private static final String PURPOSE = "admin-feedback-cursor-v1";
  private static final String FROM =
      " FROM briefing_feedback f JOIN briefing_rounds r ON r.id=f.round_id JOIN members m ON"
          + " m.id=f.member_id WHERE f.value IN ('up','down') AND r.status='published' AND"
          + " f.target_version="
          + FeedbackVersion.SQL;
  private final JdbcTemplate jdbc;
  private final ObjectMapper mapper;
  private final CsrfKeyRing keys;
  private final Clock clock;

  public AdminFeedbackService(
      JdbcTemplate jdbc, ObjectMapper mapper, CsrfKeyRing keys, Clock clock) {
    this.jdbc = jdbc;
    this.mapper = mapper;
    this.keys = keys;
    this.clock = clock;
  }

  public ObjectNode summary(String window, String start, String end) {
    var p = Period.parse(window, start, end, clock.instant());
    List<Object> args = new ArrayList<>();
    String where = where(p, args);
    var data =
        jdbc.queryForList(
            "SELECT f.feature,(f.updated_at AT TIME ZONE 'Asia/Seoul')::date AS"
                + " day,f.value,count(*) n"
                + FROM
                + where
                + " GROUP BY f.feature,day,f.value ORDER BY day",
            args.toArray());
    ObjectNode result = header(p);
    result
        .put("minSample", MIN_SAMPLE)
        .put("basis", "회원별·대상별 마지막 평가를 집계합니다. 취소·제공 중단·과거 버전은 제외하며 로컬 미리보기 평가는 포함하지 않습니다.");
    var features = result.putArray("features");
    for (String feature : List.of("briefing_round", "briefing_issue")) {
      ObjectNode item = features.addObject().put("feature", feature).put("label", label(feature));
      long up = 0, down = 0;
      Map<String, long[]> days = new TreeMap<>();
      for (var row : data)
        if (feature.equals(row.get("feature"))) {
          long n = ((Number) row.get("n")).longValue();
          boolean positive = "up".equals(row.get("value"));
          if (positive) up += n;
          else down += n;
          days.computeIfAbsent(row.get("day").toString(), k -> new long[2])[positive ? 0 : 1] += n;
        }
      item.put("up", up)
          .put("down", down)
          .put("total", up + down)
          .put("sampleHidden", up + down > 0 && up + down < MIN_SAMPLE);
      rate(item, up, down);
      var trend = item.putArray("days");
      days.forEach(
          (day, v) -> {
            var d = trend.addObject().put("date", day).put("up", v[0]).put("down", v[1]);
            rate(d, v[0], v[1]);
          });
    }
    result
        .putArray("unsupported")
        .addObject()
        .put("feature", "chatbot_answer")
        .put("label", "AI 챗봇 답변")
        .put("reason", "챗봇 평가 저장 원장은 아직 연결되지 않았습니다.");
    return result;
  }

  public ObjectNode dislikes(
      String admin,
      String window,
      String start,
      String end,
      String cursor,
      Integer requestedLimit) {
    if (requestedLimit != null && (requestedLimit < 1 || requestedLimit > 100)) invalid();
    String filters =
        Canonical.sha256(window + ":" + String.valueOf(start) + ":" + String.valueOf(end));
    var pos = FeedbackCursor.decode(mapper, keys, PURPOSE, cursor, admin, filters, requestedLimit);
    int limit = pos != null ? pos.limit() : requestedLimit == null ? 50 : requestedLimit;
    var p = Period.parse(window, start, end, pos == null ? clock.instant() : pos.asOf());
    List<Object> args = new ArrayList<>();
    String where = where(p, args) + " AND f.value='down'";
    Long total = jdbc.queryForObject("SELECT count(*)" + FROM + where, Long.class, args.toArray());
    if (pos != null) {
      where += " AND (f.updated_at,f.id COLLATE \"C\")<(?,? COLLATE \"C\")";
      try {
        args.add(Timestamp.from(Instant.parse(pos.first())));
      } catch (RuntimeException e) {
        throw new CustomException(ErrorCode.INVALID_CURSOR);
      }
      args.add(pos.last());
    }
    args.add(limit + 1);
    var rows =
        jdbc.queryForList(
            """
            SELECT f.*,r.round_date,r.edition,m.email AS owner_email,m.display_name AS owner_name,
                (SELECT i->>'title' FROM jsonb_array_elements(r.published_payload->'items') i WHERE i->>'eventId'=f.event_id) issue_title
            """
                + FROM
                + where
                + " ORDER BY f.updated_at DESC,f.id COLLATE \"C\" DESC LIMIT ?",
            args.toArray());
    ObjectNode result = mapper.createObjectNode().put("total", total).putNull("nextCursor");
    var items = result.putArray("items");
    rows.stream()
        .limit(limit)
        .forEach(
            row -> {
              String feature = (String) row.get("feature");
              String title =
                  row.get("round_date")
                      + " "
                      + ("morning".equals(row.get("edition")) ? "출근" : "퇴근")
                      + " 브리핑";
              if (row.get("issue_title") != null) title += " · " + row.get("issue_title");
              items
                  .addObject()
                  .put("at", ((Timestamp) row.get("updated_at")).toInstant().toString())
                  .put("feature", feature)
                  .put("featureLabel", label(feature))
                  .put("targetId", (String) row.get("target_id"))
                  .put("targetLabel", title)
                  .put(
                      "reason",
                      FeedbackReasonMasker.mask(
                          (String) row.get("reason"),
                          (String) row.get("owner_email"),
                          (String) row.get("owner_name")))
                  .put("voter", voter((String) row.get("member_id")))
                  .putNull("sessionId");
            });
    if (rows.size() > limit) {
      var last = rows.get(limit - 1);
      result.put(
          "nextCursor",
          FeedbackCursor.encode(
              mapper,
              keys,
              PURPOSE,
              admin,
              filters,
              limit,
              p.asOf(),
              ((Timestamp) last.get("updated_at")).toInstant().toString(),
              (String) last.get("id")));
    }
    return result;
  }

  private String voter(String member) {
    return "voter-"
        + HexFormat.of()
            .formatHex(
                keys.sign(
                        keys.activeKeyId(),
                        "admin-feedback-voter-v1",
                        member.getBytes(java.nio.charset.StandardCharsets.UTF_8))
                    .orElseThrow())
            .substring(0, 20);
  }

  private static String where(Period p, List<Object> args) {
    String w = " AND f.updated_at<=?";
    args.add(Timestamp.from(p.asOf()));
    if (p.from() != null) {
      w += " AND f.updated_at>=?";
      args.add(Timestamp.from(p.from()));
    }
    if (p.to() != null) {
      w += " AND f.updated_at<?";
      args.add(Timestamp.from(p.to()));
    }
    return w;
  }

  private ObjectNode header(Period p) {
    return mapper
        .createObjectNode()
        .put("window", p.window())
        .put("start", p.start())
        .put("end", p.end())
        .put("asOf", p.asOf().toString());
  }

  private static void rate(ObjectNode out, long up, long down) {
    if (up + down < MIN_SAMPLE) out.putNull("rate");
    else out.put("rate", up / (double) (up + down));
  }

  private static String label(String feature) {
    return feature.equals("briefing_round") ? "브리핑 회차" : "브리핑 핵심 이슈";
  }

  private static void invalid() {
    throw new CustomException(ErrorCode.INVALID_REQUEST);
  }

  record Period(String window, String start, String end, Instant asOf, Instant from, Instant to) {
    static Period parse(String window, String start, String end, Instant asOf) {
      try {
        if (!Set.of("7d", "30d", "all").contains(window)) invalid();
        LocalDate a = start == null ? null : LocalDate.parse(start),
            b = end == null ? null : LocalDate.parse(end);
        if (a != null && b != null && a.isAfter(b)) invalid();
        Instant from = a == null ? null : a.atStartOfDay(KST).toInstant();
        if (a == null && b == null && !window.equals("all"))
          from =
              asOf.atZone(KST)
                  .toLocalDate()
                  .minusDays(window.equals("7d") ? 6 : 29)
                  .atStartOfDay(KST)
                  .toInstant();
        return new Period(
            window,
            start,
            end,
            asOf,
            from,
            b == null ? null : b.plusDays(1).atStartOfDay(KST).toInstant());
      } catch (RuntimeException e) {
        throw new CustomException(ErrorCode.INVALID_REQUEST, e);
      }
    }
  }
}
