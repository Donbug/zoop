package com.zoop.briefing.personal;

import static org.mockito.Mockito.*;
import static org.mockito.ArgumentMatchers.*;
import com.zoop.auth.service.MemberSessionService.MemberPrincipal;
import java.time.*;
import java.util.List;
import org.junit.jupiter.api.Test;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.jdbc.core.RowMapper;

class PersonalBriefingDeliverySchedulerTest {
    final JdbcTemplate jdbc=mock(JdbcTemplate.class);
    final PersonalBriefingPreferences service=mock(PersonalBriefingPreferences.class);
    final Clock clock=Clock.fixed(Instant.parse("2026-11-05T00:20:30Z"),ZoneOffset.UTC);

    @Test void emptyAllowlistLeavesAllSettingsDeliveriesAndEligibilityUntouched() {
        var scheduler=new PersonalBriefingDeliveryScheduler(jdbc,service,clock,new PersonalBriefingAudience("",true));
        scheduler.captureMorning();scheduler.captureEvening();scheduler.tick();
        verifyNoInteractions(jdbc,service);
    }
    @Test @SuppressWarnings("unchecked") void captureChecksExactCohortBeforeTouchingMemberState() {
        doReturn(List.of("allowed-account","demo-account")).when(jdbc).query(anyString(),any(RowMapper.class),any(Object[].class));
        var scheduler=new PersonalBriefingDeliveryScheduler(jdbc,service,clock,new PersonalBriefingAudience("allowed-account",true));
        scheduler.captureMorning();
        verify(service).captureEligibility(new MemberPrincipal("allowed-account","scheduled"),Instant.parse("2026-11-05T00:20:00Z"));
        verifyNoMoreInteractions(service);
    }
}
