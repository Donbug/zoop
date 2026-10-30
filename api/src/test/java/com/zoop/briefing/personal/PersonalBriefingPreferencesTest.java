package com.zoop.briefing.personal;
import java.time.Instant;
import org.junit.jupiter.api.Test;
import static org.junit.jupiter.api.Assertions.*;
import static org.mockito.Mockito.*;
import org.springframework.jdbc.core.JdbcTemplate;
import java.time.Clock;
import com.zoop.briefing.storage.BriefingRoundRepository;
import com.zoop.auth.service.MemberSessionService.MemberPrincipal;
import com.zoop.common.exception.CustomException;
class PersonalBriefingPreferencesTest {
 @Test void beforeMorningUsesTodayMorning(){assertEquals(Instant.parse("2026-10-30T00:20:00Z"),PersonalBriefingPreferences.nextSlot(Instant.parse("2026-10-30T00:19:59.999999Z")));}
 @Test void atMorningCutoffUsesEvening(){assertEquals(Instant.parse("2026-10-30T08:30:00Z"),PersonalBriefingPreferences.nextSlot(Instant.parse("2026-10-30T00:20:00Z")));}
 @Test void afterMorningUsesEvening(){assertEquals(Instant.parse("2026-10-30T08:30:00Z"),PersonalBriefingPreferences.nextSlot(Instant.parse("2026-10-30T03:00:00Z")));}
 @Test void atEveningCutoffUsesNextMorning(){assertEquals(Instant.parse("2026-10-31T00:20:00Z"),PersonalBriefingPreferences.nextSlot(Instant.parse("2026-10-30T08:30:00Z")));}
 @Test void kstDateCrossingUsesLocalCalendar(){assertEquals(Instant.parse("2026-11-01T00:20:00Z"),PersonalBriefingPreferences.nextSlot(Instant.parse("2026-10-31T15:01:00Z")));}
 @Test void memberRequiredBeforeReadingPreferences(){var jdbc=mock(JdbcTemplate.class);var s=new PersonalBriefingPreferences(jdbc,Clock.systemUTC(),null,null,null,null,null,false);assertThrows(CustomException.class,()->s.settings(null));verifyNoInteractions(jdbc);}
 @Test void demoDisabledBeforeReadingAnyRoundOrStartingGeneration(){var jdbc=mock(JdbcTemplate.class);var gen=mock(SelectedGenerationService.class);var rounds=mock(BriefingRoundRepository.class);var s=new PersonalBriefingPreferences(jdbc,Clock.systemUTC(),null,gen,rounds,null,null,false);assertThrows(CustomException.class,()->s.prepare("r",new MemberPrincipal("m","s"),true,"p","req"));verifyNoInteractions(jdbc,gen,rounds);}
 @Test void legacyManualAiRequestsAreAlsoDisabledOutsideDemo(){
  var selection=mock(ExplicitBriefingService.class);var gen=mock(SelectedGenerationService.class);var controller=new ExplicitBriefingController(selection,gen);
  var request=new org.springframework.mock.web.MockHttpServletRequest();var response=new org.springframework.mock.web.MockHttpServletResponse();
  request.setAttribute(com.zoop.auth.config.MemberAuthorizationInterceptor.PRINCIPAL_ATTRIBUTE,new MemberPrincipal("m","s"));
  assertThrows(CustomException.class,()->controller.generate("r",null,request,response));
  assertThrows(CustomException.class,()->controller.retry("r","job",request,response));verifyNoInteractions(gen,selection);
 }
}
