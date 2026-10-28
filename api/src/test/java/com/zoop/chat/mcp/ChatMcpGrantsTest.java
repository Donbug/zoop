package com.zoop.chat.mcp;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.junit.jupiter.api.Assertions.assertTrue;

import com.zoop.chat.dto.ChatFrozenContext;
import com.zoop.chat.executor.ChatRun;
import com.zoop.chat.service.FrozenSelection;
import com.zoop.chat.tool.ChatCapability;
import java.nio.charset.StandardCharsets;
import java.time.Clock;
import java.time.Instant;
import java.time.ZoneOffset;
import java.util.Base64;
import java.util.List;
import org.junit.jupiter.api.Test;

/** D-AI-02: the chat MCP grant token binds one job attempt, its pinned graph and asOf, its tools and the run deadline. */
class ChatMcpGrantsTest {
    static final Instant NOW = Instant.parse("2026-10-28T03:00:00Z");
    static final String KEY_A = key('a');
    static final String KEY_B = key('b');

    @Test
    void anIssuedTokenVerifiesToItsGrant() {
        var grants = grants("k1", "k1=" + KEY_A, NOW);
        String token = grants.issue(run("job-00001", 2), List.of(ChatCapability.COMPANY_READ, ChatCapability.GRAPH_PATH_READ));

        var grant = grants.verify(token).orElseThrow();
        assertEquals("job-00001", grant.jobId());
        assertEquals(2, grant.attemptNo());
        assertEquals(List.of(ChatCapability.COMPANY_READ, ChatCapability.GRAPH_PATH_READ), grant.tools());
        assertEquals("gv-1", grant.graphVersionId());
        assertEquals(Instant.parse("2026-10-27T00:00:00Z"), grant.asOf());
        assertEquals(NOW.plusSeconds(45), grant.expiresAt());
        assertEquals(ChatMcpGrants.scope(run("job-00001", 2)), grant.scope());
        assertTrue(token.startsWith("zmcp1.k1."));
    }

    @Test
    void theSubjectScopeDiffersByMemberAndNamesNoMember() {
        String a = ChatMcpGrants.scope(run("job-00001", 1, "member-a"));
        assertFalse(a.equals(ChatMcpGrants.scope(run("job-00001", 1, "member-b"))));
        assertEquals(a, ChatMcpGrants.scope(run("job-00002", 3, "member-a")));
        String token = grants("k1", "k1=" + KEY_A, NOW).issue(run("job-00001", 1, "member-a"),
                List.of(ChatCapability.COMPANY_READ));
        String payload = new String(Base64.getUrlDecoder().decode(token.split("\\.")[2]), StandardCharsets.UTF_8);
        assertFalse(payload.contains("member-a"), payload);
    }

    @Test
    void aTamperedTruncatedOrForeignTokenIsNoGrant() {
        var grants = grants("k1", "k1=" + KEY_A, NOW);
        String token = grants.issue(run("job-00001", 1), List.of(ChatCapability.COMPANY_READ));
        String[] parts = token.split("\\.");
        String otherPayload = grants.issue(run("job-00002", 1), List.of(ChatCapability.COMPANY_READ)).split("\\.")[2];

        assertTrue(grants.verify(parts[0] + "." + parts[1] + "." + otherPayload + "." + parts[3]).isEmpty());
        assertTrue(grants.verify(token.substring(0, token.length() - 2)).isEmpty());
        assertTrue(grants.verify(token + ".x").isEmpty());
        assertTrue(grants.verify("zmcp2" + token.substring(5)).isEmpty());
        assertTrue(grants.verify(null).isEmpty());
        assertTrue(grants.verify("").isEmpty());
        var otherKey = grants("k1", "k1=" + KEY_B, NOW);
        assertTrue(otherKey.verify(token).isEmpty());
    }

    @Test
    void aTokenExpiresWithTheRunDeadline() {
        String token = grants("k1", "k1=" + KEY_A, NOW).issue(run("job-00001", 1), List.of(ChatCapability.COMPANY_READ));

        assertTrue(grants("k1", "k1=" + KEY_A, NOW.plusSeconds(44)).verify(token).isPresent());
        assertTrue(grants("k1", "k1=" + KEY_A, NOW.plusSeconds(45)).verify(token).isEmpty());
    }

    @Test
    void keysRotateTheActiveOneSignsAndListedOnesVerify() {
        String old = grants("k1", "k1=" + KEY_A, NOW).issue(run("job-00001", 1), List.of(ChatCapability.COMPANY_READ));
        var rotated = grants("k2", "k1=" + KEY_A + ",k2=" + KEY_B, NOW);

        assertTrue(rotated.verify(old).isPresent());
        String fresh = rotated.issue(run("job-00001", 1), List.of(ChatCapability.COMPANY_READ));
        assertTrue(fresh.startsWith("zmcp1.k2."));
        assertTrue(grants("k2", "k2=" + KEY_B, NOW).verify(old).isEmpty());
    }

    @Test
    void theMemberScopeReadIsNeverGranted() {
        var grants = grants("k1", "k1=" + KEY_A, NOW);
        assertThrows(IllegalArgumentException.class, () -> grants.issue(run("job-00001", 1),
                List.of(ChatCapability.COMPANY_READ, ChatCapability.PORTFOLIO_SCOPE_READ)));
        assertThrows(IllegalArgumentException.class, () -> grants.issue(run("job-00001", 1), List.of()));
    }

    @Test
    void invalidKeyConfigurationFailsWithoutNamingTheKey() {
        var tooShort = Base64.getUrlEncoder().withoutPadding().encodeToString("short".getBytes(StandardCharsets.US_ASCII));
        for (String[] config : new String[][] {{"", "k1=" + KEY_A}, {"k1", ""}, {"k1", "k2=" + KEY_A},
                {"k1", "k1=" + tooShort}, {"k1", "k1=" + KEY_A + ",k1=" + KEY_B}, {"k1", "k1=%%%"}, {"k 1", "k 1=" + KEY_A}}) {
            var error = assertThrows(IllegalArgumentException.class, () -> grants(config[0], config[1], NOW));
            assertFalse(error.getMessage().contains(KEY_A));
        }
    }

    static ChatMcpGrants grants(String active, String keys, Instant now) {
        return new ChatMcpGrants(active, keys, Clock.fixed(now, ZoneOffset.UTC));
    }

    static ChatRun run(String jobId, int attemptNo) {
        return run(jobId, attemptNo, "member-a");
    }

    static ChatRun run(String jobId, int attemptNo, String memberId) {
        var context = new ChatFrozenContext(List.of(), 0, null, Instant.parse("2026-10-27T00:00:00Z"), "gv-1");
        return new ChatRun(jobId, "conv-0001", memberId, attemptNo, "run",
                List.of(new ChatRun.Turn(jobId, "질문", null, null)), context, FrozenSelection.NONE, "gv-1", 0, NOW,
                NOW.plusSeconds(45));
    }

    static String key(char fill) {
        return Base64.getUrlEncoder().withoutPadding().encodeToString(String.valueOf(fill).repeat(32)
                .getBytes(StandardCharsets.US_ASCII));
    }
}
