package com.zoop.feedback;

import com.zoop.admin.auth.config.AdminAuthorizationInterceptor;
import com.zoop.admin.auth.service.AdminPrincipal;
import io.swagger.v3.oas.annotations.Operation;
import io.swagger.v3.oas.annotations.media.Content;
import io.swagger.v3.oas.annotations.media.Schema;
import io.swagger.v3.oas.annotations.responses.ApiResponse;
import jakarta.servlet.http.HttpServletRequest;
import org.springframework.web.bind.annotation.*;
import tools.jackson.databind.node.ObjectNode;

/**
 * A-ADM-02b / FS066-02. Only confirmed member votes from PostgreSQL; no fabricated zeroes for
 * unconnected features.
 */
@RestController
@RequestMapping("/api/v1/admin/feedback")
public class AdminFeedbackController {
  private final AdminFeedbackService feedback;

  public AdminFeedbackController(AdminFeedbackService feedback) {
    this.feedback = feedback;
  }

  @ApiResponse(
      responseCode = "200",
      content =
          @Content(
              mediaType = "application/json",
              schema = @Schema(implementation = FeedbackHttpSchemas.Summary.class)))
  @GetMapping("/summary")
  @Operation(operationId = "getFeedbackSummary", summary = "브리핑 회원 평가 요약·일별 추이")
  public ObjectNode summary(
      @RequestParam(defaultValue = "all") String window,
      @RequestParam(required = false) String start,
      @RequestParam(required = false) String end) {
    return feedback.summary(window, start, end);
  }

  @ApiResponse(
      responseCode = "200",
      content =
          @Content(
              mediaType = "application/json",
              schema = @Schema(implementation = FeedbackHttpSchemas.Dislikes.class)))
  @GetMapping("/dislikes")
  @Operation(operationId = "listDislikedResults", summary = "브리핑 싫어요 사유 목록")
  public ObjectNode dislikes(
      @RequestParam(defaultValue = "all") String window,
      @RequestParam(required = false) String start,
      @RequestParam(required = false) String end,
      @RequestParam(required = false) String cursor,
      @RequestParam(required = false) Integer limit,
      HttpServletRequest request) {
    var admin =
        (AdminPrincipal) request.getAttribute(AdminAuthorizationInterceptor.PRINCIPAL_ATTRIBUTE);
    return feedback.dislikes(admin.adminId(), window, start, end, cursor, limit);
  }
}
