package com.zoop.chat.controller;

import com.zoop.auth.config.MemberAuthorizationInterceptor;
import com.zoop.auth.service.MemberSessionService.MemberPrincipal;
import com.zoop.chat.dto.ChatConversation;
import com.zoop.chat.dto.ChatCurrentResponse;
import com.zoop.chat.dto.ChatJob;
import com.zoop.chat.dto.ChatJobRequest;
import com.zoop.chat.dto.ChatSessionResponse;
import com.zoop.chat.service.ChatResponseGuard;
import com.zoop.chat.service.ChatService;
import com.zoop.common.request.RequestIdFilter;
import io.swagger.v3.oas.annotations.Operation;
import jakarta.servlet.http.HttpServletRequest;
import org.springframework.http.HttpStatus;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.PutMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestHeader;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;
import tools.jackson.databind.JsonNode;

/**
 * D-AI-01, D-AI-01b, D-AI-02, D-AI-02b: member conversations and question jobs (OpenAPI tag {@code chat}). Every job it
 * returns passes {@link ChatResponseGuard}, outside the service transaction, so evidence access is re-checked on each return.
 */
@RestController
@RequestMapping("/api/v1/chat")
public class ChatController {
    private final ChatService service;
    private final ChatResponseGuard guard;

    public ChatController(ChatService service, ChatResponseGuard guard) {
        this.service = service;
        this.guard = guard;
    }

    @PutMapping("/sessions/{id}")
    @Operation(operationId = "createConversation", summary = "새 대화 생성")
    public ResponseEntity<ChatSessionResponse> createConversation(@PathVariable String id, HttpServletRequest request) {
        var result = service.createSession(principal(request), id);
        return ResponseEntity.status(result.created() ? HttpStatus.CREATED : HttpStatus.OK).body(result.session());
    }

    @GetMapping("/sessions/current")
    @Operation(operationId = "getCurrentConversation", summary = "최신 대화 복원",
            description = "저장된 최신 대화만 회수한다. 모델을 호출하지 않는다.")
    public ChatCurrentResponse getCurrentConversation(HttpServletRequest request) {
        return guard.current(service.getCurrentConversation(principal(request)), RequestIdFilter.currentId(request));
    }

    @GetMapping("/sessions/{id}")
    @Operation(operationId = "getConversation", summary = "대화와 질문 작업 조회")
    public ChatConversation getConversation(@PathVariable String id, HttpServletRequest request) {
        return guard.conversation(service.getConversation(principal(request), id), RequestIdFilter.currentId(request));
    }

    @PostMapping("/sessions/{id}/jobs")
    @Operation(operationId = "submitQuestion", summary = "질문 접수·맥락 고정·비동기 분석",
            description = "최초 접수에서 질문과 맥락을 고정한다. Idempotency-Key는 jobId와 같아야 한다.")
    public ResponseEntity<ChatJob> submitQuestion(@PathVariable String id, @RequestBody JsonNode body,
            @RequestHeader("Idempotency-Key") String idempotencyKey, HttpServletRequest request) {
        var result = service.submit(principal(request), id, idempotencyKey, ChatJobRequest.parse(body));
        return ResponseEntity.status(result.accepted() ? HttpStatus.ACCEPTED : HttpStatus.OK)
                .body(guard.job(result.job(), RequestIdFilter.currentId(request)));
    }

    @GetMapping("/jobs/{jobId}")
    @Operation(operationId = "getQuestionJob", summary = "질문 작업 상태·저장 결과 회수",
            description = "저장된 상태만 회수한다. 모델을 호출하지 않는다.")
    public ChatJob getQuestionJob(@PathVariable String jobId, HttpServletRequest request) {
        return guard.job(service.getJob(principal(request), jobId), RequestIdFilter.currentId(request));
    }

    @PostMapping("/jobs/{jobId}/retry")
    @Operation(operationId = "retryQuestionJob", summary = "허용된 실패만 같은 질문 작업 재시도")
    public ResponseEntity<ChatJob> retryQuestionJob(@PathVariable String jobId,
            @RequestHeader("Idempotency-Key") String idempotencyKey, HttpServletRequest request) {
        var result = service.retry(principal(request), jobId, idempotencyKey);
        return ResponseEntity.status(result.accepted() ? HttpStatus.ACCEPTED : HttpStatus.OK)
                .body(guard.job(result.job(), RequestIdFilter.currentId(request)));
    }

    @PostMapping("/jobs/{jobId}/cancel")
    @Operation(operationId = "cancelQuestionJob", summary = "질문 작업 명시적 취소")
    public ChatJob cancelQuestionJob(@PathVariable String jobId, @RequestHeader("Idempotency-Key") String idempotencyKey,
            HttpServletRequest request) {
        return guard.job(service.cancel(principal(request), jobId, idempotencyKey), RequestIdFilter.currentId(request));
    }

    private static MemberPrincipal principal(HttpServletRequest request) {
        return (MemberPrincipal) request.getAttribute(MemberAuthorizationInterceptor.PRINCIPAL_ATTRIBUTE);
    }
}
