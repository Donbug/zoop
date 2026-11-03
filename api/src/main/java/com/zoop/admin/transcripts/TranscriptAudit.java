package com.zoop.admin.transcripts;

import com.zoop.admin.auth.service.AdminPrincipal;
import com.zoop.common.exception.CustomException;
import com.zoop.common.exception.ErrorCode;
import java.sql.Timestamp;
import java.time.Clock;
import java.util.Map;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Component;
import org.springframework.transaction.annotation.Propagation;
import org.springframework.transaction.annotation.Transactional;
import tools.jackson.databind.ObjectMapper;

/** Commits before returning to the reader, including denied/failed reads that roll back. */
@Component
public class TranscriptAudit {
    private final JdbcTemplate jdbc;
    private final ObjectMapper mapper;
    private final Clock clock;
    public TranscriptAudit(JdbcTemplate jdbc, ObjectMapper mapper, Clock clock) {
        this.jdbc = jdbc; this.mapper = mapper; this.clock = clock;
    }

    @Transactional(propagation = Propagation.REQUIRES_NEW)
    public void record(AdminPrincipal admin, String target, String purpose, String outcome, String requestId,
            String only, Integer limit, int returned, Map<String, Integer> counts) {
        try {
            var detail = mapper.createObjectNode();
            if (only != null) detail.put("only", only);
            if (limit != null) detail.put("limit", limit);
            detail.put("returned", returned).set("maskingCounts", mapper.valueToTree(counts));
            int inserted = jdbc.update("""
                    INSERT INTO audit_logs(actor_kind,admin_id,actor_id,actor_email_snapshot,action,target_type,
                        target_id,outcome,purpose,reason,request_id,detail,occurred_at)
                    VALUES('admin',?,?,?,'transcript.view',?,?,?,?,?, ?,?::jsonb,?)
                    """, admin.adminId(), admin.adminId(), admin.email(),
                    target == null ? "chat_session_list" : "chat_session", target, outcome, purpose, null,
                    requestId, mapper.writeValueAsString(detail), Timestamp.from(clock.instant()));
            if (inserted != 1) throw new IllegalStateException("Audit not confirmed");
        } catch (RuntimeException error) {
            // No driver error/parameters (and therefore no conversation data) enter the error chain.
            throw new CustomException(ErrorCode.AUDIT_UNAVAILABLE);
        }
    }
}
