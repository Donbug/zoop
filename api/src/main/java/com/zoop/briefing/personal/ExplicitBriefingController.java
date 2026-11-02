package com.zoop.briefing.personal;
import com.zoop.auth.config.MemberAuthorizationInterceptor;
import com.zoop.auth.service.MemberSessionService.MemberPrincipal;
import com.zoop.common.request.RequestIdFilter;
import org.springframework.web.bind.annotation.*;
import jakarta.servlet.http.*;
import tools.jackson.databind.node.ObjectNode;
@RestController
public class ExplicitBriefingController {
    private final ExplicitBriefingService service;
    private final SelectedGenerationService generation;
    @org.springframework.beans.factory.annotation.Value("${zoop.briefing.personal-demo-enabled:false}") private boolean demoEnabled;
    public ExplicitBriefingController(ExplicitBriefingService s,SelectedGenerationService generation){service=s;this.generation=generation;}
    @GetMapping("/api/v1/briefings/personalization/options")
    public ObjectNode options(@RequestParam(defaultValue="false")boolean importMine,HttpServletRequest r,HttpServletResponse response){
        response.setHeader("Cache-Control","no-store");response.setHeader("Vary","Cookie");return service.options(member(r),importMine);
    }
    @PostMapping("/api/v1/briefings/{id}/personalized/selection")
    public ObjectNode select(@PathVariable String id,@RequestBody ExplicitBriefingService.Choice c,HttpServletRequest r,HttpServletResponse response){
        response.setHeader("Cache-Control","no-store");response.setHeader("Vary","Cookie");return service.select(id,member(r),c,RequestIdFilter.currentId(r));
    }
    @PostMapping("/api/v1/briefings/{id}/personalized/generations")
    public ObjectNode generate(@PathVariable String id,@RequestBody SelectedGenerationService.Request body,HttpServletRequest r,HttpServletResponse response){
        response.setHeader("Cache-Control","no-store");response.setHeader("Vary","Cookie");if(!demoEnabled)throw new com.zoop.common.exception.CustomException(com.zoop.common.exception.ErrorCode.ACCESS_DENIED);return generation.create(id,member(r),body,RequestIdFilter.currentId(r));
    }
    @GetMapping("/api/v1/briefings/{id}/personalized/generations/{jobId}")
    public ObjectNode generation(@PathVariable String id,@PathVariable String jobId,HttpServletRequest r,HttpServletResponse response){
        response.setHeader("Cache-Control","no-store");response.setHeader("Vary","Cookie");return generation.get(id,jobId,member(r),RequestIdFilter.currentId(r));
    }
    @PostMapping("/api/v1/briefings/{id}/personalized/generations/{jobId}/retry")
    public ObjectNode retry(@PathVariable String id,@PathVariable String jobId,HttpServletRequest r,HttpServletResponse response){
        response.setHeader("Cache-Control","no-store");response.setHeader("Vary","Cookie");if(!demoEnabled)throw new com.zoop.common.exception.CustomException(com.zoop.common.exception.ErrorCode.ACCESS_DENIED);return generation.retry(id,jobId,member(r),RequestIdFilter.currentId(r));
    }
    private MemberPrincipal member(HttpServletRequest r){return (MemberPrincipal)r.getAttribute(MemberAuthorizationInterceptor.PRINCIPAL_ATTRIBUTE);}
}
