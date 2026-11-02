package com.zoop.feedback;

import com.zoop.auth.service.CsrfKeyRing;
import com.zoop.briefing.query.BriefingQueryService;
import com.zoop.briefing.storage.BriefingRoundRepository;
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
  private final BriefingRoundRepository rounds;
  private final BriefingQueryService publicRead;
  private final AiResultFeedbackService aiResults;

  public AdminFeedbackService(
      JdbcTemplate jdbc, ObjectMapper mapper, CsrfKeyRing keys, Clock clock,
      BriefingRoundRepository rounds, BriefingQueryService publicRead, AiResultFeedbackService aiResults) {
    this.jdbc = jdbc;
    this.mapper = mapper;
    this.keys = keys;
    this.clock = clock;
    this.rounds = rounds;
    this.publicRead = publicRead;
    this.aiResults = aiResults;
  }

  private static final List<String> FEATURES=List.of("briefing_round","briefing_issue","chatbot_answer","news_summary");

  public ObjectNode summary(String window, String start, String end) {
    var p=Period.parse(window,start,end,clock.instant());
    var rows=currentRows(p);
    ObjectNode result=header(p).put("minSample",MIN_SAMPLE)
        .put("basis","회원별·대상별 마지막 평가를 집계합니다. 취소·제공 중단·과거 버전·현재 열 수 없는 결과와 로컬 미리보기 평가는 제외합니다.");
    var features=result.putArray("features");
    for(String feature:FEATURES){
      ObjectNode item=features.addObject().put("feature",feature).put("label",label(feature));
      long up=0,down=0;Map<String,long[]> days=new TreeMap<>();
      for(var row:rows)if(feature.equals(row.get("feature"))){
        boolean positive="up".equals(row.get("value"));if(positive)up++;else down++;
        String day=((Timestamp)row.get("updated_at")).toInstant().atZone(KST).toLocalDate().toString();
        days.computeIfAbsent(day,k->new long[2])[positive?0:1]++;
      }
      item.put("up",up).put("down",down).put("total",up+down).put("sampleHidden",up+down>0&&up+down<MIN_SAMPLE);
      rate(item,up,down);var trend=item.putArray("days");
      days.forEach((day,counts)->{var d=trend.addObject().put("date",day).put("up",counts[0]).put("down",counts[1]);rate(d,counts[0],counts[1]);});
    }
    result.putArray("unsupported");return result;
  }

  /** Evaluate readability before totals, aggregation and pagination, across all four result kinds. */
  private List<Map<String,Object>> currentRows(Period p){
    List<Object> args=new ArrayList<>();String where=readableWhere(p,args);
    var rows=new ArrayList<>(jdbc.queryForList("""
      SELECT f.*,r.round_date,r.edition,m.email AS owner_email,m.display_name AS owner_name,
        (SELECT i->>'title' FROM jsonb_array_elements(r.published_payload->'items') i WHERE i->>'eventId'=f.event_id) issue_title
      """+FROM+where,args.toArray()));
    for(var row:aiResults.currentRows(null,p.asOf())){
      var at=((Timestamp)row.get("updated_at")).toInstant();
      if(!Set.of("up","down").contains(row.get("value")) || p.from()!=null&&at.isBefore(p.from()) || p.to()!=null&&!at.isBefore(p.to()))continue;
      rows.add(row);
    }
    return rows;
  }

  public ObjectNode dislikes(String admin,String window,String start,String end,String cursor,Integer requestedLimit){
    if(requestedLimit!=null&&(requestedLimit<1||requestedLimit>100))invalid();
    String filters=Canonical.sha256(window+":"+String.valueOf(start)+":"+String.valueOf(end));
    var pos=FeedbackCursor.decode(mapper,keys,PURPOSE,cursor,admin,filters,requestedLimit);
    int limit=pos!=null?pos.limit():requestedLimit==null?50:requestedLimit;
    var p=Period.parse(window,start,end,pos==null?clock.instant():pos.asOf());
    var rows=currentRows(p).stream().filter(r->"down".equals(r.get("value")))
        .sorted(Comparator.<Map<String,Object>,Instant>comparing(r->((Timestamp)r.get("updated_at")).toInstant()).reversed()
            .thenComparing(r->cursorId(r),Comparator.reverseOrder())).toList();
    long total=rows.size();
    if(pos!=null){
      final Instant at;
      try{at=Instant.parse(pos.first());}catch(RuntimeException e){throw new CustomException(ErrorCode.INVALID_CURSOR);}
      rows=rows.stream().filter(r->{int cmp=((Timestamp)r.get("updated_at")).toInstant().compareTo(at);return cmp<0||cmp==0&&cursorId(r).compareTo(pos.last())<0;}).toList();
    }
    ObjectNode result=mapper.createObjectNode().put("total",total).putNull("nextCursor");var items=result.putArray("items");
    for(var row:rows.stream().limit(limit).toList()){
      String feature=row.get("feature").toString();
      String title=AiResultFeedbackService.FEATURES.contains(feature)?label(feature):row.get("round_date")+" "+("morning".equals(row.get("edition"))?"출근":"퇴근")+" 브리핑";
      if(row.get("issue_title")!=null)title+=" · "+row.get("issue_title");
      items.addObject().put("id",row.get("id").toString()).put("feature",feature).put("featureLabel",label(feature))
        .put("targetId",row.get("target_id").toString()).put("targetVersion",row.get("target_version").toString())
        .put("targetLabel",title).put("reason",FeedbackReasonMasker.mask((String)row.get("reason"),(String)row.get("owner_email"),(String)row.get("owner_name")))
        .put("at",((Timestamp)row.get("updated_at")).toInstant().toString()).put("voter",voter(row.get("member_id").toString())).putNull("sessionId");
    }
    if(rows.size()>limit){var last=rows.get(limit-1);result.put("nextCursor",FeedbackCursor.encode(mapper,keys,PURPOSE,admin,filters,limit,p.asOf(),((Timestamp)last.get("updated_at")).toInstant().toString(),cursorId(last)));}
    return result;
  }
  private static String cursorId(Map<String,Object> row){return row.get("feature")+"/"+row.get("id");}

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

  /** Filter BEFORE grouping, counts and keyset paging; one current rights check per candidate round. */
  private String readableWhere(Period p, List<Object> args) {
    String where = where(p, args);
    var candidates = jdbc.queryForList("SELECT DISTINCT r.id" + FROM + where, args.toArray());
    List<String> readable = new ArrayList<>();
    for (var candidate : candidates) {
      String id = (String) candidate.get("id");
      var round = rounds.findById(id).orElseThrow();
      if (publicRead.isCurrentlyReadable(round, "admin-feedback")) readable.add(id);
    }
    if (readable.isEmpty()) return where + " AND false";
    args.addAll(readable);
    return where + " AND r.id IN (" + String.join(",", Collections.nCopies(readable.size(), "?")) + ")";
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
    return switch(feature){case "briefing_round" -> "브리핑 회차";case "briefing_issue" -> "브리핑 핵심 이슈";case "chatbot_answer" -> "AI 챗봇 답변";case "news_summary" -> "뉴스 요약";default -> throw new CustomException(ErrorCode.INVALID_REQUEST);};
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
