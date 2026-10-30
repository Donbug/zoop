package com.zoop.feedback;

import com.zoop.auth.config.MemberAuthorizationInterceptor;
import com.zoop.auth.service.MemberSessionService.MemberPrincipal;
import com.zoop.common.request.RequestIdFilter;
import io.swagger.v3.oas.annotations.Operation;
import io.swagger.v3.oas.annotations.media.Content;
import io.swagger.v3.oas.annotations.media.Schema;
import io.swagger.v3.oas.annotations.responses.ApiResponse;
import jakarta.servlet.http.HttpServletRequest;
import org.springframework.web.bind.annotation.*;
import tools.jackson.databind.JsonNode;
import tools.jackson.databind.node.ObjectNode;

@RestController
@RequestMapping("/api/v1/feedback")
public class MemberFeedbackController {
  private final MemberFeedbackService feedback;

  public MemberFeedbackController(MemberFeedbackService feedback) {
    this.feedback = feedback;
  }

  @ApiResponse(
      responseCode = "200",
      content =
          @Content(
              mediaType = "application/json",
              schema = @Schema(implementation = FeedbackHttpSchemas.Item.class)))
  @io.swagger.v3.oas.annotations.parameters.RequestBody(
      content =
          @Content(
              mediaType = "application/json",
              schema = @Schema(implementation = FeedbackHttpSchemas.Vote.class)))
  @PutMapping
  @Operation(operationId = "setFeedback", summary = "회원 브리핑 도움 됨·안 됨·이유 저장")
  public ObjectNode put(@RequestBody JsonNode body, HttpServletRequest request) {
    return feedback.put(principal(request), body, RequestIdFilter.currentId(request));
  }

  @ApiResponse(
      responseCode = "200",
      content =
          @Content(
              mediaType = "application/json",
              schema = @Schema(implementation = FeedbackHttpSchemas.Page.class)))
  @GetMapping
  @Operation(operationId = "getMyFeedback", summary = "본인의 유효 브리핑 평가 조회")
  public ObjectNode get(
      @RequestParam(required = false) String feature,
      @RequestParam(required = false) String targetIds,
      @RequestParam(required = false) String cursor,
      @RequestParam(required = false) Integer limit,
      HttpServletRequest request) {
    return feedback.list(principal(request).memberId(), feature, targetIds, cursor, limit);
  }

  private MemberPrincipal principal(HttpServletRequest request) {
    return (MemberPrincipal)
        request.getAttribute(MemberAuthorizationInterceptor.PRINCIPAL_ATTRIBUTE);
  }
}
