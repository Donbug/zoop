package com.zoop.chat.tool;

import java.util.Arrays;
import java.util.Optional;

/**
 * The logical read capabilities of the chatbot and the MCP registry group each belongs to (design summary 5.1). Listing a
 * capability does not make it callable: only one bound to a tool in {@link ChatToolRegistry} is executed, and a model's
 * free-form tool name is never mapped to anything.
 */
public enum ChatCapability {
    HELP_SEARCH("help.search", "zoop-help-read"),
    SCREEN_SPEC_READ("screenSpec.read", "zoop-help-read"),
    ZOOP_POLICY_READ("zoopPolicy.read", "zoop-help-read"),
    COMPANY_READ("company.read", "zoop-core-read"),
    DOCUMENT_SEARCH("document.search", "zoop-core-read"),
    ISSUE_READ("issue.read", "zoop-core-read"),
    EVIDENCE_RESOLVE("evidence.resolve", "zoop-core-read"),
    PERIOD_COMPARE("period.compare", "zoop-core-read"),
    SELECTION_RULE_READ("selectionRule.read", "zoop-core-read"),
    GRAPH_PATH_READ("graph.path.read", "zoop-graph-read"),
    GRAPH_VERSION_DIFF("graph.version.diff", "zoop-graph-read"),
    BRIEFING_READ("briefing.read", "zoop-briefing-read"),
    BRIEFING_EVIDENCE("briefing.evidence", "zoop-briefing-read"),
    PORTFOLIO_SCOPE_READ("portfolio.scope.read", "zoop-member-scope-read");

    private final String id;
    private final String group;

    ChatCapability(String id, String group) {
        this.id = id;
        this.group = group;
    }

    public String id() {
        return id;
    }

    public String group() {
        return group;
    }

    public static Optional<ChatCapability> of(String id) {
        return Arrays.stream(values()).filter(c -> c.id.equals(id)).findFirst();
    }
}
