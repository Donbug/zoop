package com.zoop.admin.briefings;

import java.nio.file.Path;
import java.util.List;
import java.util.Map;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Component;
import tools.jackson.databind.ObjectMapper;

/** A-ADM-04: only an operator-admitted input and configured worker enable processing. */
@Component
public class BriefingReprocessPolicy {
    final boolean enabled, allowLive;
    final Path root;
    final List<String> command;
    final JdbcTemplate jdbc;
    public BriefingReprocessPolicy(JdbcTemplate jdbc, ObjectMapper mapper,
            @Value("${zoop.briefing.reprocess.enabled:false}") boolean enabled,
            @Value("${zoop.briefing.reprocess.allow-live:false}") boolean allowLive,
            @Value("${zoop.briefing.reprocess.root:}") String root,
            @Value("${zoop.briefing.reprocess.command:[]}") String command) {
        this.jdbc=jdbc;this.enabled=enabled;this.allowLive=allowLive;
        this.root=root.isBlank()?null:Path.of(root).toAbsolutePath().normalize();
        var parsed=mapper.readTree(command);
        if(!parsed.isArray() || parsed.size()>16) throw new IllegalArgumentException("Invalid reprocess command");
        this.command=java.util.stream.StreamSupport.stream(parsed.spliterator(),false).map(n->{
            if(!n.isTextual() || n.asText().isBlank())throw new IllegalArgumentException("Invalid reprocess command");return n.asText();}).toList();
        if(enabled && (this.root==null || this.command.isEmpty()))throw new IllegalArgumentException("Reprocess root and command required");
    }
    public String blocked(String roundId) {
        if(!enabled)return "재처리 실행기가 설정되지 않았습니다.";
        var r=jdbc.queryForList("SELECT status,published_at,scheduled_at,lease_until FROM briefing_rounds WHERE id=?",roundId);
        if(r.isEmpty())return "회차가 없습니다.";
        var row=r.getFirst();
        if(row.get("published_at")!=null)return "이미 발행한 회차는 재처리할 수 없습니다.";
        if(jdbc.queryForObject("SELECT count(*) FROM briefing_reprocess_jobs WHERE round_id=? AND status IN ('queued','running')",Integer.class,roundId)>0)return "이 회차를 이미 재처리하고 있습니다.";
        if(jdbc.queryForObject("SELECT count(*) FROM briefing_attempts WHERE round_id=? AND status IN ('queued','running','verifying') AND lease_until>clock_timestamp()",Integer.class,roundId)>0)return "진행 중인 생성 시도가 있습니다.";
        if(jdbc.queryForObject("SELECT scheduled_at>clock_timestamp() FROM briefing_rounds WHERE id=?",Boolean.class,roundId))return "예정 시각이 지난 미발행 회차만 재처리할 수 있습니다.";
        var inputs=jdbc.queryForList("SELECT operation FROM briefing_reprocess_inputs WHERE round_id=? AND enabled",roundId);
        if(inputs.isEmpty())return "고정된 생성 입력 또는 검증된 저장 복구 결과가 필요합니다.";
        if(inputs.getFirst().get("operation").equals("generation") && !allowLive)return "실제 모델 호출을 사용하는 재처리가 승인되지 않았습니다.";
        return null;
    }
    public String latestState(String roundId){
        var rows=jdbc.queryForList("SELECT status FROM briefing_reprocess_jobs WHERE round_id=? ORDER BY created_at DESC,id DESC LIMIT 1",String.class,roundId);
        return rows.isEmpty()?null:rows.getFirst();
    }
}
