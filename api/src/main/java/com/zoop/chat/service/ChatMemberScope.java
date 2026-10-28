package com.zoop.chat.service;

import java.util.ArrayList;
import java.util.HashMap;
import java.util.LinkedHashSet;
import java.util.List;
import java.util.Map;
import java.util.Set;

import com.zoop.auth.service.MemberSessionService.MemberPrincipal;
import com.zoop.graph.read.PersonalCompanies;
import org.springframework.jdbc.core.namedparam.MapSqlParameterSource;
import org.springframework.jdbc.core.namedparam.NamedParameterJdbcTemplate;
import org.springframework.stereotype.Component;

/**
 * A member's own companies for Q07 (decision of 2026-10-27), the same ones the personal map shows
 * ({@link PersonalCompanies}): the holdings of the connected mock account in its order, then the watchlist in the member's
 * order, each company once, with its catalog name. The member is the authenticated job's, never one a question or a model
 * names.
 */
@Component
public class ChatMemberScope {
    /** One of the member's companies and why it is theirs. */
    public record Company(String id, String name, boolean held, boolean watched) {
        /** "보유", "관심" or "보유·관심". */
        public String relation() {
            return held && watched ? "보유·관심" : held ? "보유" : "관심";
        }
    }

    /** The job reads the member's data under no session of its own. */
    static final String SESSION = "chat-job";

    private final PersonalCompanies personal;
    private final NamedParameterJdbcTemplate jdbc;

    public ChatMemberScope(PersonalCompanies personal, NamedParameterJdbcTemplate jdbc) {
        this.personal = personal;
        this.jdbc = jdbc;
    }

    /**
     * Held companies first, then watched ones. Throws {@link com.zoop.common.exception.CustomException} or a data access
     * exception when they cannot be read.
     */
    public List<Company> of(String memberId) {
        var ids = personal.of(new MemberPrincipal(memberId, SESSION));
        Set<String> held = Set.copyOf(ids.holdings());
        Set<String> watched = Set.copyOf(ids.watchlist());
        Set<String> all = new LinkedHashSet<>(ids.holdings());
        all.addAll(ids.watchlist());
        if (all.isEmpty()) return List.of();
        Map<String, String> names = new HashMap<>();
        jdbc.query("SELECT id, name FROM companies WHERE id IN (:ids)", new MapSqlParameterSource("ids", all),
                rs -> {
                    names.put(rs.getString("id"), rs.getString("name"));
                });
        List<Company> companies = new ArrayList<>();
        for (String id : all) {
            companies.add(new Company(id, names.getOrDefault(id, id), held.contains(id), watched.contains(id)));
        }
        return companies;
    }
}
