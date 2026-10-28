package com.zoop.chat.tool;

import com.zoop.chat.service.ChatZoopDocs;
import java.util.Arrays;
import java.util.List;
import java.util.Optional;

/**
 * The logical read capabilities of the chatbot and the tool registry group each belongs to (design summary 5.1). Listing a
 * capability does not make it callable: only one bound to a tool in {@link ChatToolRegistry} is executed, and a model's
 * free-form tool name is never mapped to anything.
 */
public enum ChatCapability {
    HELP_SEARCH("help.search", "zoop-help-read", "ZOOP 도움말 검색"),
    SCREEN_SPEC_READ("screenSpec.read", "zoop-help-read", "ZOOP 화면 설명 읽기"),
    ZOOP_POLICY_READ("zoopPolicy.read", "zoop-help-read", "ZOOP 서비스 이용약관과 개인정보 처리방침 읽기"),
    COMPANY_READ("company.read", "zoop-core-read", "기업과 그 기업의 승인된 관계, 관계를 뒷받침하는 근거 읽기"),
    DOCUMENT_SEARCH("document.search", "zoop-core-read", "기업 뉴스·공시 문서 검색"),
    ISSUE_READ("issue.read", "zoop-core-read", "사건(이슈)과 관련 기업, 사건 근거 읽기"),
    EVIDENCE_RESOLVE("evidence.resolve", "zoop-core-read", "근거 문서의 인용 구간 확인"),
    PERIOD_COMPARE("period.compare", "zoop-core-read", "두 기간의 변화 비교"),
    SELECTION_RULE_READ("selectionRule.read", "zoop-core-read", "사건·관계·브리핑 선정 규칙 읽기"),
    GRAPH_PATH_READ("graph.path.read", "zoop-graph-read", "기업 사이의 관계 경로 탐색"),
    GRAPH_VERSION_DIFF("graph.version.diff", "zoop-graph-read", "그래프 버전 사이의 차이 계산"),
    BRIEFING_READ("briefing.read", "zoop-briefing-read", "발행된 출근·퇴근 브리핑 읽기"),
    BRIEFING_EVIDENCE("briefing.evidence", "zoop-briefing-read", "브리핑 항목의 근거 읽기"),
    PORTFOLIO_SCOPE_READ("portfolio.scope.read", "zoop-member-scope-read", "회원 본인의 보유·관심 종목 범위 확인");

    private final String id;
    private final String group;
    private final String description;

    ChatCapability(String id, String group, String description) {
        this.id = id;
        this.group = group;
        this.description = description;
    }

    /** What the capability reads, in the words the router model is asked about. Never an id the model could call. */
    public String description() {
        return description;
    }

    public String id() {
        return id;
    }

    public String group() {
        return group;
    }

    /** Whether its reads need the run's pinned public graph; ZOOP's own documents do not. */
    public boolean readsGraph() {
        return !"zoop-help-read".equals(group);
    }

    /**
     * The documents a ZOOP document capability always reads, whatever the question or the selection names (the router cannot
     * name a document); none for any other capability, which reads the requirement's targets.
     */
    public List<String> documents() {
        return this == ZOOP_POLICY_READ ? ChatZoopDocs.POLICIES : List.of();
    }

    /** What a capability that can read the whole public graph reads when its requirement names nothing. */
    public static final String WHOLE_GRAPH = "graph:public";
    /** The only target of a member-scope read: the run's own member, which the server injects. */
    public static final String MEMBER_SELF = "member:self";

    /**
     * The targets the capability reads when the requirement names none and nothing is selected: the whole public graph for
     * {@code graph.version.diff} ("what changed on the map"), the run's own member for {@code portfolio.scope.read}; none
     * for any other capability, which then needs a target.
     */
    public List<String> untargeted() {
        return switch (this) {
            case GRAPH_VERSION_DIFF -> List.of(WHOLE_GRAPH);
            case PORTFOLIO_SCOPE_READ -> List.of(MEMBER_SELF);
            default -> List.of();
        };
    }

    public static Optional<ChatCapability> of(String id) {
        return Arrays.stream(values()).filter(c -> c.id.equals(id)).findFirst();
    }
}
