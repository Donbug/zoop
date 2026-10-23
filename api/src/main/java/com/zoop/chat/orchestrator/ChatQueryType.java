package com.zoop.chat.orchestrator;

import static com.zoop.chat.tool.ChatCapability.*;

import com.zoop.chat.tool.ChatCapability;
import java.util.EnumSet;
import java.util.Set;

/**
 * The Q01 to Q08 capability tags (design summary 4) and the logical capabilities each may use: the server allowlist a routed
 * capability must pass. A question may carry several tags. Q02 (general concepts) uses no tool: it is answered as a
 * {@code general_knowledge} section and never stands in for a current fact.
 */
public enum ChatQueryType {
    Q01(HELP_SEARCH, SCREEN_SPEC_READ, ZOOP_POLICY_READ),
    Q02(),
    Q03(COMPANY_READ, DOCUMENT_SEARCH, ISSUE_READ, EVIDENCE_RESOLVE),
    Q04(GRAPH_PATH_READ, EVIDENCE_RESOLVE),
    Q05(PERIOD_COMPARE, GRAPH_VERSION_DIFF, EVIDENCE_RESOLVE),
    Q06(BRIEFING_READ, BRIEFING_EVIDENCE),
    Q07(PORTFOLIO_SCOPE_READ, COMPANY_READ, ISSUE_READ, GRAPH_PATH_READ, EVIDENCE_RESOLVE),
    Q08(SELECTION_RULE_READ, EVIDENCE_RESOLVE);

    private final Set<ChatCapability> capabilities;

    ChatQueryType(ChatCapability... capabilities) {
        this.capabilities = capabilities.length == 0 ? Set.of() : Set.copyOf(EnumSet.of(capabilities[0], capabilities));
    }

    public Set<ChatCapability> capabilities() {
        return capabilities;
    }
}
