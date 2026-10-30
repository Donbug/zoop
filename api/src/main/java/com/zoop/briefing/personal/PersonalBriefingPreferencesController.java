package com.zoop.briefing.personal;
import com.zoop.auth.config.MemberAuthorizationInterceptor;
import com.zoop.auth.service.MemberSessionService.MemberPrincipal;
import com.zoop.common.request.RequestIdFilter;
import jakarta.servlet.http.*;
import org.springframework.web.bind.annotation.*;
import tools.jackson.databind.node.ObjectNode;
@RestController
public class PersonalBriefingPreferencesController {
 private final PersonalBriefingPreferences service;
 public PersonalBriefingPreferencesController(PersonalBriefingPreferences service){this.service=service;}
 private MemberPrincipal member(HttpServletRequest r,HttpServletResponse s){s.setHeader("Cache-Control","no-store");s.setHeader("Vary","Cookie");return (MemberPrincipal)r.getAttribute(MemberAuthorizationInterceptor.PRINCIPAL_ATTRIBUTE);}
 @GetMapping("/api/v1/briefings/personalization/settings") public ObjectNode settings(HttpServletRequest r,HttpServletResponse s){return service.settings(member(r,s));}
 @PostMapping("/api/v1/briefings/personalization/settings/initialize") public ObjectNode initialize(HttpServletRequest r,HttpServletResponse s){return service.initialize(member(r,s));}
 @PutMapping("/api/v1/briefings/personalization/settings") public ObjectNode save(@RequestBody PersonalBriefingPreferences.Save b,HttpServletRequest r,HttpServletResponse s){return service.save(member(r,s),b);}
 @GetMapping("/api/v1/briefings/{id}/personalized/delivery") public ObjectNode delivery(@PathVariable String id,@RequestParam(defaultValue="false")boolean demo,HttpServletRequest r,HttpServletResponse s){return service.get(id,member(r,s),demo,RequestIdFilter.currentId(r));}
 public record Preview(String preferenceRevision){}
 @PostMapping("/api/v1/briefings/{id}/personalized/demo") public ObjectNode demo(@PathVariable String id,@RequestBody Preview b,HttpServletRequest r,HttpServletResponse s){return service.prepare(id,member(r,s),true,b.preferenceRevision(),RequestIdFilter.currentId(r));}
}
