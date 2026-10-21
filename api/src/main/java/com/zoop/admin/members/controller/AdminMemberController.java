package com.zoop.admin.members.controller;

import com.zoop.admin.auth.config.AdminAuthorizationInterceptor;
import com.zoop.admin.auth.service.AdminPrincipal;
import com.zoop.admin.members.dto.MemberAdminResponse.MemberDetail;
import com.zoop.admin.members.dto.MemberAdminResponse.MemberList;
import com.zoop.admin.members.dto.MemberAdminResponse.MemberStatusResult;
import com.zoop.admin.members.dto.MemberStatusRequest;
import com.zoop.admin.members.service.AdminMemberQueryService;
import com.zoop.admin.members.service.AdminMemberStatusService;
import com.zoop.common.request.RequestIdFilter;
import io.swagger.v3.oas.annotations.Operation;
import jakarta.servlet.http.HttpServletRequest;
import jakarta.validation.Valid;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestHeader;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

@RestController
@RequestMapping("/api/v1/admin/members")
public class AdminMemberController {
    private final AdminMemberQueryService queries;
    private final AdminMemberStatusService statuses;

    public AdminMemberController(AdminMemberQueryService queries, AdminMemberStatusService statuses) {
        this.queries = queries;
        this.statuses = statuses;
    }

    @GetMapping
    @Operation(operationId = "listMembers", summary = "회원 활동 목록 조회")
    public MemberList list(@RequestParam(required = false) String status,
            @RequestParam(required = false) String q,
            @RequestParam(required = false) String cursor,
            @RequestParam(required = false) Integer limit,
            HttpServletRequest request) {
        return queries.list(status, q, cursor, limit, RequestIdFilter.currentId(request));
    }

    @GetMapping("/{memberId}")
    @Operation(operationId = "getMemberActivity", summary = "회원 활동 상세 조회")
    public MemberDetail detail(@PathVariable String memberId, HttpServletRequest request) {
        return queries.detail(memberId, RequestIdFilter.currentId(request));
    }

    @PostMapping("/{memberId}/block")
    @Operation(operationId = "blockMember", summary = "회원 차단 및 세션 회수")
    public MemberStatusResult block(@PathVariable String memberId,
            @RequestHeader("Idempotency-Key") String idempotencyKey,
            @Valid @RequestBody MemberStatusRequest body, HttpServletRequest request) {
        return statuses.block(memberId, body, idempotencyKey, principal(request), RequestIdFilter.currentId(request));
    }

    @PostMapping("/{memberId}/unblock")
    @Operation(operationId = "unblockMember", summary = "회원 차단 해제")
    public MemberStatusResult unblock(@PathVariable String memberId,
            @RequestHeader("Idempotency-Key") String idempotencyKey,
            @Valid @RequestBody MemberStatusRequest body, HttpServletRequest request) {
        return statuses.unblock(memberId, body, idempotencyKey, principal(request), RequestIdFilter.currentId(request));
    }

    private static AdminPrincipal principal(HttpServletRequest request) {
        Object principal = request.getAttribute(AdminAuthorizationInterceptor.PRINCIPAL_ATTRIBUTE);
        if (principal instanceof AdminPrincipal admin) return admin;
        throw new IllegalStateException("AdminAuthorizationInterceptor must run before controller");
    }
}
