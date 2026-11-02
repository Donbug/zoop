package com.zoop.admin.briefings;

import com.zoop.admin.auth.config.AdminAuthorizationInterceptor;
import com.zoop.admin.auth.service.AdminPrincipal;
import com.zoop.common.exception.CustomException;
import com.zoop.common.exception.ErrorCode;
import com.zoop.common.request.RequestIdFilter;
import io.swagger.v3.oas.annotations.Operation;
import jakarta.servlet.http.HttpServletRequest;
import jakarta.validation.Valid;
import jakarta.validation.constraints.NotBlank;
import jakarta.validation.constraints.Size;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.*;
import tools.jackson.databind.node.ObjectNode;

@RestController
@RequestMapping("/api/v1/admin/briefings")
public class AdminBriefingReprocessController {
    private final AdminBriefingReprocessService service;
    public AdminBriefingReprocessController(AdminBriefingReprocessService service){this.service=service;}
    @io.swagger.v3.oas.annotations.media.Schema(name="AdminBriefingReprocessRequest")
    public record Request(@NotBlank @Size(max=500) String reason){}
    @PostMapping("/{roundId}/reprocess")
    @Operation(operationId="reprocessBriefingRound",summary="미발행 회차의 새 생성 시도 접수")
    public ResponseEntity<ObjectNode> post(@PathVariable String roundId,@Valid @RequestBody Request body,HttpServletRequest request){
        var keys=request.getHeaders("Idempotency-Key");
        if(!keys.hasMoreElements())throw new CustomException(ErrorCode.INVALID_REQUEST);
        String key=keys.nextElement();
        if(keys.hasMoreElements() || key.isBlank() || key.length()>200 || key.chars().anyMatch(Character::isISOControl))throw new CustomException(ErrorCode.INVALID_REQUEST);
        return ResponseEntity.accepted().body(service.submit(roundId,body.reason(),key,
            (AdminPrincipal)request.getAttribute(AdminAuthorizationInterceptor.PRINCIPAL_ATTRIBUTE),RequestIdFilter.currentId(request)));
    }
}
