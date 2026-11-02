package com.zoop.chat.tool;

import java.util.Set;
import java.util.HashSet;
import org.springframework.stereotype.Component;

/**
 * {@code briefing.evidence} (Q06): the evidence of the issues of one published briefing round. Where {@code briefing.read}
 * shares its evidence limit across the whole round, this read spends it on the issues the targets name after the round
 * ({@link ChatBriefingRound}), or on the round's issues when none is named. It reads through {@link BriefingReadTool#round}, so
 * a round that is not published has nothing to read and evidence is passed on only when readable now. An issue the round did
 * not carry is simply not found: this read never reaches evidence past what the round published.
 */
@Component
public class BriefingEvidenceTool implements ChatTool {
    private final BriefingReadTool rounds;

    public BriefingEvidenceTool(BriefingReadTool rounds) {
        this.rounds = rounds;
    }

    @Override
    public ChatCapability capability() {
        return ChatCapability.BRIEFING_EVIDENCE;
    }

    @Override
    public ChatToolOutput read(ChatToolScope scope, ChatToolRequest request) {
        Set<String> issues = new HashSet<>(request.targets().subList(1, request.targets().size()));
        if (issues.stream().anyMatch(ChatBriefingRound::isRef)) {
            throw new IllegalArgumentException("a briefing read names one round");
        }
        return rounds.round(scope, request, issue -> issues.isEmpty() || issues.contains(issue.path("eventId").asString()));
    }
}
