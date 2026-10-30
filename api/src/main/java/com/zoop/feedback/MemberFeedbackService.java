package com.zoop.feedback;

import com.zoop.auth.service.CsrfKeyRing;
import com.zoop.auth.service.MemberSessionService.MemberPrincipal;
import com.zoop.briefing.query.BriefingQueryService;
import com.zoop.briefing.storage.BriefingRoundRepository;
import com.zoop.common.exception.CustomException;
import com.zoop.common.exception.ErrorCode;
import com.zoop.common.json.Canonical;
import java.sql.Timestamp;
import java.time.Clock;
import java.time.Instant;
import java.util.*;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Isolation;
import org.springframework.transaction.annotation.Transactional;
import tools.jackson.databind.JsonNode;
import tools.jackson.databind.ObjectMapper;
import tools.jackson.databind.node.ObjectNode;

@Service
public class MemberFeedbackService {
  private static final Set<String> FEATURES = Set.of("briefing_round", "briefing_issue", "chatbot_answer", "news_summary");
  private static final String PURPOSE = "member-feedback-cursor-v1";
  private final JdbcTemplate jdbc;
  private final BriefingRoundRepository rounds;
  private final BriefingQueryService publicRead;
  private final FeedbackVersion versions;
  private final ObjectMapper mapper;
  private final CsrfKeyRing keys;
  private final Clock clock;
  private final AiResultFeedbackService aiResults;

  public MemberFeedbackService(
      JdbcTemplate jdbc,
      BriefingRoundRepository rounds,
      BriefingQueryService publicRead,
      FeedbackVersion versions,
      ObjectMapper mapper,
      CsrfKeyRing keys,
      Clock clock, AiResultFeedbackService aiResults) {
    this.jdbc = jdbc;
    this.rounds = rounds;
    this.publicRead = publicRead;
    this.versions = versions;
    this.mapper = mapper;
    this.keys = keys;
    this.clock = clock;
    this.aiResults = aiResults;
  }

  @Transactional
  public ObjectNode put(MemberPrincipal member, JsonNode body, String requestId) {
    if (!body.isObject()
        || !Set.of("feature", "targetId", "targetVersion", "value", "reason")
            .containsAll(body.propertyNames())) invalid();
    String feature = text(body, "feature", false),
        target = text(body, "targetId", false),
        version = text(body, "targetVersion", true);
    String value = text(body, "value", false), reason = text(body, "reason", true);
    if (!FEATURES.contains(feature)
        || !validTarget(target)
        || version == null
        || version.isBlank()
        || version.length() > 300
        || !Set.of("up", "down", "none").contains(value)) invalid();
    if (reason != null
        && (!value.equals("down")
            || reason.length() > 200
            || reason
                .codePoints()
                .anyMatch(c -> Character.isISOControl(c) && c != '\n' && c != '\t'))) invalid();
    if (reason != null) {
      reason = reason.strip();
      if (reason.isEmpty()) reason = null;
    }
    if (AiResultFeedbackService.FEATURES.contains(feature)) return aiResults.put(member,feature,target,version,value,reason);
    var owners =
        jdbc.queryForList("SELECT status FROM members WHERE id=? FOR SHARE", member.memberId());
    if (owners.isEmpty() || !"active".equals(owners.getFirst().get("status")))
      throw new CustomException(ErrorCode.MEMBER_BLOCKED);
    var old =
        jdbc.queryForList(
            "SELECT * FROM briefing_feedback WHERE member_id=? AND feature=? AND target_id=? FOR"
                + " UPDATE",
            member.memberId(),
            feature,
            target);
    if (value.equals("none") && !old.isEmpty()) {
      if (!version.equals(old.getFirst().get("target_version"))) conflict();
      jdbc.update(
          "UPDATE briefing_feedback SET value='none',reason=NULL,updated_at=? WHERE id=? AND"
              + " value<>'none'",
          Timestamp.from(clock.instant()),
          old.getFirst().get("id"));
      return out(
          jdbc.queryForMap("SELECT * FROM briefing_feedback WHERE id=?", old.getFirst().get("id")));
    }
    String roundId, eventId = null;
    if (feature.equals("briefing_round")) roundId = target;
    else {
      var matches =
          jdbc.queryForList(
              """
              SELECT r.id, i->>'eventId' AS event_id FROM briefing_rounds r,
              LATERAL jsonb_array_elements(r.published_payload->'items') i
              WHERE ?=r.id||'/'||(i->>'eventId')
              """,
              target);
      if (matches.size() != 1) throw new CustomException(ErrorCode.RESOURCE_NOT_FOUND);
      roundId = (String) matches.getFirst().get("id");
      eventId = (String) matches.getFirst().get("event_id");
    }
    if (jdbc.queryForList("SELECT id FROM briefing_rounds WHERE id=? FOR SHARE", roundId).isEmpty())
      throw new CustomException(ErrorCode.RESOURCE_NOT_FOUND);
    var round = rounds.findById(roundId).orElseThrow();
    if (round.publishedAt() == null || !round.status().equals("published")) conflict();
    // Same current rights, provenance and digest checks as the public reader; no model is called.
    var visible = publicRead.get(round.date(), round.edition(), requestId);
    if (!roundId.equals(visible.path("id").asText()) || !version.equals(versions.get(roundId)))
      conflict();
    Instant now = clock.instant();
    jdbc.update(
        """
        INSERT INTO briefing_feedback(id,member_id,feature,target_id,target_version,round_id,event_id,value,reason,created_at,updated_at)
        VALUES(?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(member_id,feature,target_id) DO UPDATE
        SET target_version=excluded.target_version,value=excluded.value,reason=excluded.reason,updated_at=excluded.updated_at
        WHERE (briefing_feedback.target_version,briefing_feedback.value,briefing_feedback.reason)
            IS DISTINCT FROM (excluded.target_version,excluded.value,excluded.reason)
        """,
        UUID.randomUUID().toString(),
        member.memberId(),
        feature,
        target,
        version,
        roundId,
        eventId,
        value,
        reason,
        Timestamp.from(now),
        Timestamp.from(now));
    return out(
        jdbc.queryForMap(
            "SELECT * FROM briefing_feedback WHERE member_id=? AND feature=? AND target_id=?",
            member.memberId(),
            feature,
            target));
  }

  @Transactional(readOnly = true, isolation = Isolation.REPEATABLE_READ)
  public ObjectNode list(
      String member, String feature, String targetIds, String cursor, Integer requestedLimit) {
    if (feature != null && !FEATURES.contains(feature)
        || requestedLimit != null && (requestedLimit < 1 || requestedLimit > 100)) invalid();
    List<String> targets =
        targetIds == null
            ? List.of()
            : Arrays.stream(targetIds.split(",", -1)).sorted().distinct().toList();
    if (targets.size() > 100 || targets.stream().anyMatch(t -> !validTarget(t))) invalid();
    String filters = Canonical.sha256(String.valueOf(feature) + ":" + String.join(",", targets));
    var pos = FeedbackCursor.decode(mapper, keys, PURPOSE, cursor, member, filters, requestedLimit);
    int limit = pos != null ? pos.limit() : requestedLimit == null ? 50 : requestedLimit;
    Instant asOf = pos == null ? clock.instant() : pos.asOf();
    List<Object> args = new ArrayList<>(List.of(member, Timestamp.from(asOf)));
    StringBuilder sql =
        new StringBuilder(
            "SELECT f.* FROM (SELECT b.id,b.member_id,b.feature,b.target_id,b.target_version,b.value,b.reason,b.created_at,b.updated_at FROM briefing_feedback b JOIN briefing_rounds r ON r.id=b.round_id WHERE b.target_version="
                + FeedbackVersion.SQL + " UNION ALL SELECT a.id,a.member_id,a.feature,a.target_id,a.target_version,a.value,a.reason,a.created_at,a.updated_at FROM ai_result_feedback a WHERE false) f WHERE f.member_id=? AND f.updated_at<=?");
    var eligible = feature == null || AiResultFeedbackService.FEATURES.contains(feature) ? aiResults.currentRows(member,asOf).stream().map(r -> r.get("id").toString()).toList() : List.<String>of();
    if (!eligible.isEmpty()) {
      String ids = String.join(",", Collections.nCopies(eligible.size(), "?"));
      int index = sql.indexOf("WHERE false");
      sql.replace(index,index+"WHERE false".length(),"WHERE a.id IN ("+ids+")");
      args.addAll(0,eligible);
    }
    if (feature != null) {
      sql.append(" AND f.feature=?");
      args.add(feature);
    }
    if (!targets.isEmpty()) {
      sql.append(
          " AND f.target_id IN ("
              + String.join(",", Collections.nCopies(targets.size(), "?"))
              + ")");
      args.addAll(targets);
    }
    if (pos != null) {
      sql.append(" AND (f.feature COLLATE \"C\",f.target_id COLLATE \"C\")>(?,?)");
      args.add(pos.first());
      args.add(pos.last());
    }
    sql.append(" ORDER BY f.feature COLLATE \"C\",f.target_id COLLATE \"C\" LIMIT ?");
    args.add(limit + 1);
    var rows = jdbc.queryForList(sql.toString(), args.toArray());
    ObjectNode result = mapper.createObjectNode();
    var items = result.putArray("items");
    rows.stream().limit(limit).forEach(r -> items.add(out(r)));
    result.putNull("nextCursor");
    if (rows.size() > limit) {
      var last = rows.get(limit - 1);
      result.put(
          "nextCursor",
          FeedbackCursor.encode(
              mapper,
              keys,
              PURPOSE,
              member,
              filters,
              limit,
              asOf,
              (String) last.get("feature"),
              (String) last.get("target_id")));
    }
    return result;
  }

  private ObjectNode out(Map<String, Object> row) {
    return mapper
        .createObjectNode()
        .put("feature", (String) row.get("feature"))
        .put("targetId", (String) row.get("target_id"))
        .put("targetVersion", (String) row.get("target_version"))
        .put("value", (String) row.get("value"))
        .put("reason", (String) row.get("reason"));
  }

  private static String text(JsonNode node, String field, boolean nullable) {
    JsonNode value = node.get(field);
    if (value == null || value.isNull()) {
      if (nullable) return null;
      invalid();
    }
    if (!value.isTextual()) invalid();
    return value.asText();
  }

  private static boolean validTarget(String text) {
    return text != null
        && text.length() <= 600
        && text.matches("[A-Za-z0-9._:/\\\\-]+")
        && !text.isBlank();
  }

  private static void invalid() {
    throw new CustomException(ErrorCode.INVALID_REQUEST);
  }

  private static void conflict() {
    throw new CustomException(ErrorCode.REVISION_CONFLICT);
  }
}
