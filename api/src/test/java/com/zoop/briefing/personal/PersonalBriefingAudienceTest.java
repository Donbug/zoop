package com.zoop.briefing.personal;

import static org.junit.jupiter.api.Assertions.*;
import org.junit.jupiter.api.Test;

class PersonalBriefingAudienceTest {
    @Test void anEmptyCohortNeverOptsAnyoneIntoAutomaticOrRestrictedPaidWork() {
        var audience=new PersonalBriefingAudience("",true);
        assertTrue(audience.memberIds().isEmpty());
        assertFalse(audience.automatic("demo-account"));
        assertFalse(audience.additionalGeneration("demo-account"));
    }
    @Test void onlyExactListedMembersAreEligible() {
        var audience=new PersonalBriefingAudience(" member-b,member-a ",true);
        assertEquals(java.util.List.of("member-a","member-b"),audience.memberIds());
        assertTrue(audience.automatic("member-a"));
        assertTrue(audience.additionalGeneration("member-b"));
        assertFalse(audience.automatic("member"));
        assertFalse(audience.additionalGeneration("demo-account"));
    }
    @Test void wildcardOrMalformedConfigurationCannotBecomeAllMembers() {
        for(String text:java.util.List.of("*","a,","a,a","a@invalid","a\nb"))
            assertThrows(IllegalArgumentException.class,()->new PersonalBriefingAudience(text,true));
    }
    @Test void legacyManualGenerationOptInDoesNotOptEveryoneIntoTheScheduler() {
        var audience=new PersonalBriefingAudience("",false);
        assertTrue(audience.additionalGeneration("legacy-owner"));
        assertFalse(audience.automatic("legacy-owner"));
    }
}
