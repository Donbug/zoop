package com.zoop.admin.transcripts;

import java.sql.ResultSet;
import java.sql.SQLException;
import java.sql.Timestamp;
import java.time.Instant;
import java.util.ArrayList;
import java.util.List;
import java.util.Optional;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Repository;

@Repository
public class JdbcTranscriptRepository implements TranscriptRepository {
    private final JdbcTemplate jdbc;
    public JdbcTranscriptRepository(JdbcTemplate jdbc) { this.jdbc = jdbc; }

    private static final String DISLIKED = """
            AND EXISTS (SELECT 1 FROM ai_result_feedback f JOIN chat_jobs j ON j.id=f.chat_job_id
                WHERE j.session_id=s.id AND f.member_id=s.member_id
                  AND f.feature='chatbot_answer' AND f.value='down' AND f.updated_at<=?)
            """;
    private static String where(String only, Instant asOf, List<Object> args) {
        args.add(Timestamp.from(asOf));
        if ("disliked".equals(only)) { args.add(Timestamp.from(asOf)); return " WHERE s.created_at<=? " + DISLIKED; }
        return " WHERE s.created_at<=? ";
    }

    @Override public long total(String only, Instant asOf) {
        var args = new ArrayList<Object>();
        return jdbc.queryForObject("SELECT count(*) FROM chat_sessions s" + where(only, asOf, args), Long.class, args.toArray());
    }

    @Override public List<Summary> list(String only, Instant asOf, Instant beforeAt, String beforeId, int limit) {
        var args = new ArrayList<Object>();
        // Correlated aggregate subqueries avoid multiplying votes by other jobs in the session.
        for (int n = 0; n < 3; n++) args.add(Timestamp.from(asOf));
        String sql = """
                SELECT s.id,s.member_id,m.email,m.display_name,s.created_at,
                  COALESCE((SELECT max(j.asked_at) FROM chat_jobs j WHERE j.session_id=s.id AND j.asked_at<=?),s.created_at) last_at,
                  (SELECT count(*) FROM chat_jobs j WHERE j.session_id=s.id AND j.asked_at<=?) messages,
                  COALESCE((SELECT j.question FROM chat_jobs j WHERE j.session_id=s.id AND j.asked_at<=? ORDER BY j.seq LIMIT 1),'') preview,
                  (SELECT count(*) FROM ai_result_feedback f JOIN chat_jobs j ON j.id=f.chat_job_id
                    WHERE j.session_id=s.id AND f.member_id=s.member_id AND f.feature='chatbot_answer' AND f.value='up') up,
                  (SELECT count(*) FROM ai_result_feedback f JOIN chat_jobs j ON j.id=f.chat_job_id
                    WHERE j.session_id=s.id AND f.member_id=s.member_id AND f.feature='chatbot_answer' AND f.value='down') down
                FROM chat_sessions s JOIN members m ON m.id=s.member_id
                """ + where(only, asOf, args);
        if (beforeAt != null) {
            sql += " AND (s.created_at,s.id)<(?,?)";
            args.add(Timestamp.from(beforeAt)); args.add(beforeId);
        }
        sql += " ORDER BY s.created_at DESC,s.id DESC LIMIT ?";
        args.add(limit);
        return jdbc.query(sql, (r, n) -> new Summary(session(r), r.getTimestamp("last_at").toInstant(),
                r.getInt("messages"), r.getString("preview"), r.getLong("up"), r.getLong("down")), args.toArray());
    }

    @Override public Optional<Session> find(String sessionId) {
        return jdbc.query("""
                SELECT s.id,s.member_id,m.email,m.display_name,s.created_at
                FROM chat_sessions s JOIN members m ON m.id=s.member_id WHERE s.id=?
                """, (r, n) -> session(r), sessionId).stream().findFirst();
    }

    private static Session session(ResultSet r) throws SQLException {
        return new Session(r.getString("id"),
                new TranscriptMasker.Owner(r.getString("member_id"), r.getString("email"), r.getString("display_name")),
                r.getTimestamp("created_at").toInstant());
    }

    @Override public List<Job> jobs(String sessionId) {
        return jdbc.query("""
                SELECT id,seq,asked_at,question,status,outcome,result::text,failure::text,frozen_context::text
                FROM chat_jobs WHERE session_id=? ORDER BY seq
                """, (r, n) -> new Job(r.getString("id"), r.getInt("seq"), r.getTimestamp("asked_at").toInstant(),
                r.getString("question"), r.getString("status"), r.getString("outcome"), r.getString("result"),
                r.getString("failure"), r.getString("frozen_context")), sessionId);
    }

    @Override public List<Vote> votes(String sessionId) {
        return jdbc.query("""
                SELECT f.chat_job_id,f.value,f.reason FROM ai_result_feedback f
                JOIN chat_jobs j ON j.id=f.chat_job_id JOIN chat_sessions s ON s.id=j.session_id
                WHERE s.id=? AND f.member_id=s.member_id AND f.feature='chatbot_answer' AND f.value IN ('up','down')
                ORDER BY j.seq,f.updated_at,f.id
                """, (r, n) -> new Vote(r.getString("chat_job_id"), r.getString("value"), r.getString("reason")), sessionId);
    }
}
