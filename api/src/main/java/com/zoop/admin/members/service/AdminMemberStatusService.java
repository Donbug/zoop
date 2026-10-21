package com.zoop.admin.members.service;

import java.time.Clock;
import java.time.Instant;
import java.util.UUID;

import com.zoop.admin.auth.repository.AdminAuditRepository;
import com.zoop.admin.auth.service.AdminPrincipal;
import com.zoop.admin.audit.AuditReasonPolicy;
import com.zoop.admin.members.dto.MemberAdminResponse.MemberStatusResult;
import com.zoop.admin.members.dto.MemberStatusRequest;
import com.zoop.admin.members.repository.AdminMemberRepository;
import com.zoop.common.exception.CustomException;
import com.zoop.common.exception.ErrorCode;
import com.zoop.common.json.Canonical;
import org.springframework.dao.DataAccessException;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;
import tools.jackson.databind.ObjectMapper;

@Service
public class AdminMemberStatusService {
    private final AdminMemberRepository repository;
    private final AdminAuditRepository audit;
    private final AdminMemberQueryService queries;
    private final ObjectMapper mapper;
    private final Clock clock;

    public AdminMemberStatusService(AdminMemberRepository repository, AdminAuditRepository audit,
            AdminMemberQueryService queries, ObjectMapper mapper, Clock clock) {
        this.repository = repository;
        this.audit = audit;
        this.queries = queries;
        this.mapper = mapper;
        this.clock = clock;
    }

    @Transactional
    public MemberStatusResult block(String memberId, MemberStatusRequest request, String idempotencyKey,
            AdminPrincipal admin, String requestId) {
        return change(memberId, request, idempotencyKey, admin, requestId, "blocked", "member.block");
    }

    @Transactional
    public MemberStatusResult unblock(String memberId, MemberStatusRequest request, String idempotencyKey,
            AdminPrincipal admin, String requestId) {
        return change(memberId, request, idempotencyKey, admin, requestId, "active", "member.unblock");
    }

    private MemberStatusResult change(String memberId, MemberStatusRequest request, String idempotencyKey,
            AdminPrincipal admin, String requestId, String targetStatus, String action) {
        validateKey(idempotencyKey);
        String reason = request.reason().strip();
        if (!AuditReasonPolicy.safeMemberReason(reason)) {
            throw new CustomException(ErrorCode.INVALID_REQUEST);
        }
        String path = "/api/v1/admin/members/" + memberId + "/" + (targetStatus.equals("blocked") ? "block" : "unblock");
        String requestHash = Canonical.sha256(memberId + "\n" + targetStatus + "\n"
                + request.expectedRevision() + "\n" + reason);
        Instant now = clock.instant();
        try {
            boolean claimed = repository.claimIdempotency(UUID.randomUUID().toString(), admin.adminId(), path,
                    idempotencyKey, requestHash, now);
            var idempotency = repository.findIdempotencyForUpdate(admin.adminId(), path, idempotencyKey)
                    .orElseThrow(() -> new IllegalStateException("Claimed idempotency record is missing"));
            if (!idempotency.requestHash().equals(requestHash)) {
                throw new CustomException(ErrorCode.IDEMPOTENCY_CONFLICT);
            }
            if (!claimed) {
                if (!"completed".equals(idempotency.status()) || idempotency.responseBody() == null) {
                    throw new CustomException(ErrorCode.SOURCE_UNAVAILABLE, true);
                }
                return mapper.readValue(idempotency.responseBody(), MemberStatusResult.class);
            }

            var current = repository.findStatusForUpdate(memberId)
                    .orElseThrow(() -> new CustomException(ErrorCode.RESOURCE_NOT_FOUND));
            if (current.revision() != request.expectedRevision()) {
                throw new CustomException(ErrorCode.REVISION_CONFLICT);
            }
            boolean changed = !current.status().equals(targetStatus);
            if (changed) {
                Instant blockedAt = targetStatus.equals("blocked") ? now : null;
                if (!repository.updateStatus(memberId, current.revision(), targetStatus, blockedAt, now)) {
                    throw new CustomException(ErrorCode.REVISION_CONFLICT);
                }
                if (targetStatus.equals("blocked")) repository.revokeActiveSessions(memberId, now);
                audit.recordMemberStatusAction(admin.adminId(), admin.email(), action, memberId, reason,
                        current.status(), targetStatus, current.revision(), current.revision() + 1, requestId, now);
            }
            MemberStatusResult result = new MemberStatusResult(changed, queries.detailAt(memberId, now, requestId));
            repository.completeIdempotency(idempotency.id(), 200, mapper.writeValueAsString(result));
            return result;
        } catch (CustomException exception) {
            throw exception;
        } catch (DataAccessException exception) {
            throw new CustomException(ErrorCode.SOURCE_UNAVAILABLE, exception);
        } catch (Exception exception) {
            throw new IllegalStateException("Unable to persist member status result", exception);
        }
    }

    private static void validateKey(String key) {
        if (key == null || key.isBlank() || key.length() > 200 || key.chars().anyMatch(Character::isISOControl)) {
            throw new CustomException(ErrorCode.INVALID_REQUEST);
        }
    }
}
