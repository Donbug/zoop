package com.zoop.admin.pipeline;

import com.zoop.admin.pipeline.GraphRoundAdminResponse.GraphRoundDetail;
import com.zoop.admin.pipeline.GraphRoundAdminResponse.GraphRoundList;
import io.swagger.v3.oas.annotations.Operation;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import com.zoop.admin.auth.service.AdminPrincipal;
import com.zoop.admin.auth.config.AdminAuthorizationInterceptor;
import com.zoop.admin.pipeline.GraphRoundAdminResponse.GraphRoundOut;
import com.zoop.common.request.RequestIdFilter;
import jakarta.servlet.http.HttpServletRequest;
import org.springframework.http.HttpStatus;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestHeader;
import org.springframework.web.bind.annotation.ResponseStatus;
import org.springframework.web.bind.annotation.RestController;

/**
 * The round-level view of A-ADM-03 (#55): rounds and their timelines, and the two commands the scheduler brings (a retry of a
 * failed round, a manual start). Both commands are 404 while no scheduler runs in this application.
 */
@RestController
@RequestMapping("/api/v1/admin/pipeline/rounds")
public class GraphRoundAdminController {
    private final GraphRoundAdminService service;
    private final GraphRoundAdminCommandService commands;

    public GraphRoundAdminController(GraphRoundAdminService service, GraphRoundAdminCommandService commands) {
        this.service = service;
        this.commands = commands;
    }

    @PostMapping
    @ResponseStatus(HttpStatus.ACCEPTED)
    @Operation(operationId = "startGraphRound", summary = "그래프 정기 회차 수동 시작")
    public GraphRoundOut start(@RequestHeader("Idempotency-Key") String idempotencyKey,
            @RequestBody(required = false) GraphRoundStartRequest body, HttpServletRequest request) {
        return commands.start(body, idempotencyKey, principal(request), RequestIdFilter.currentId(request));
    }

    @PostMapping("/{roundId}/retry")
    @ResponseStatus(HttpStatus.ACCEPTED)
    @Operation(operationId = "retryGraphRound", summary = "실패한 그래프 정기 회차 재시도")
    public GraphRoundOut retry(@PathVariable String roundId, @RequestHeader("Idempotency-Key") String idempotencyKey,
            HttpServletRequest request) {
        return commands.retry(roundId, idempotencyKey, principal(request), RequestIdFilter.currentId(request));
    }

    private static AdminPrincipal principal(HttpServletRequest request) {
        Object principal = request.getAttribute(AdminAuthorizationInterceptor.PRINCIPAL_ATTRIBUTE);
        if (principal instanceof AdminPrincipal admin) return admin;
        throw new IllegalStateException("AdminAuthorizationInterceptor must run before controller");
    }

    @GetMapping
    @Operation(operationId = "listGraphRounds", summary = "그래프 정기 회차 목록 조회")
    public GraphRoundList list(@RequestParam(required = false) String stage, @RequestParam(required = false) String cursor,
            @RequestParam(required = false) Integer limit) {
        return service.list(stage, cursor, limit);
    }

    @GetMapping("/{roundId}")
    @Operation(operationId = "getGraphRound", summary = "그래프 정기 회차 상세·이력 조회")
    public GraphRoundDetail get(@PathVariable String roundId) {
        return service.get(roundId);
    }
}
