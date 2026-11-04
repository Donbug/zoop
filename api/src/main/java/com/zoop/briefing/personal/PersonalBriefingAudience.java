package com.zoop.briefing.personal;

import java.util.Arrays;
import java.util.List;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Component;

/** Operator cohort for automatic delivery. A page read never opts a member into paid work. */
@Component
public class PersonalBriefingAudience {
    private final List<String> members;
    private final boolean generationRestricted;

    public PersonalBriefingAudience(
            @Value("${zoop.briefing.personal-scheduler-member-ids:}") String memberIds,
            @Value("${zoop.briefing.personal-generation-allowlist-required:false}") boolean generationRestricted) {
        var values = memberIds.isBlank() ? List.<String>of()
                : Arrays.stream(memberIds.split(",", -1)).map(String::trim).toList();
        if (values.size() > 1000 || values.stream().anyMatch(id -> !id.matches("[A-Za-z0-9_-]{1,256}"))
                || values.stream().distinct().count() != values.size())
            throw new IllegalArgumentException("invalid_personal_briefing_cohort");
        this.members = values.stream().sorted().toList();
        this.generationRestricted = generationRestricted;
    }

    public List<String> memberIds() { return members; }
    public boolean automatic(String memberId) { return members.contains(memberId); }
    public boolean additionalGeneration(String memberId) {
        return !generationRestricted || automatic(memberId);
    }
}
