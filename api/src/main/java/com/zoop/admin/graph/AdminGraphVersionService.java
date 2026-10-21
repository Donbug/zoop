package com.zoop.admin.graph;

import java.nio.charset.StandardCharsets;
import java.time.Clock;
import java.time.Instant;
import java.util.Base64;
import java.util.UUID;

import com.zoop.admin.audit.AuditReasonPolicy;
import com.zoop.admin.auth.repository.AdminAuditRepository;
import com.zoop.admin.auth.service.AdminPrincipal;
import com.zoop.admin.graph.GraphVersionAdminResponse.ActivateResponse;
import com.zoop.admin.graph.GraphVersionAdminResponse.GraphVersionList;
import com.zoop.common.exception.CustomException;
import com.zoop.common.exception.ErrorCode;
import com.zoop.common.json.Canonical;
import com.zoop.graph.snapshot.GraphSnapshotStore;
import com.zoop.graph.version.GraphVersionRecord;
import com.zoop.graph.version.JdbcGraphVersionRepository;
import org.springframework.dao.DataAccessException;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;
import tools.jackson.databind.ObjectMapper;

/**
 * Lists public graph versions and moves the public pointer for an administrator (FS059). A version is activated only
 * after its snapshot loads and verifies through the configured {@link GraphSnapshotStore}, so the pointer never moves
 * to a version the public read API would answer with 503.
 */
@Service
public class AdminGraphVersionService {
    private static final int DEFAULT_LIMIT = 50;
    private static final int MAX_LIMIT = 100;
    private static final String CURSOR_PREFIX = "gv1:";

    private final JdbcAdminGraphVersionRepository repository;
    private final JdbcGraphVersionRepository versions;
    private final GraphSnapshotStore snapshots;
    private final AdminAuditRepository audit;
    private final ObjectMapper mapper;
    private final Clock clock;

    public AdminGraphVersionService(JdbcAdminGraphVersionRepository repository, JdbcGraphVersionRepository versions,
            GraphSnapshotStore snapshots, AdminAuditRepository audit, ObjectMapper mapper, Clock clock) {
        this.repository = repository;
        this.versions = versions;
        this.snapshots = snapshots;
        this.audit = audit;
        this.mapper = mapper;
        this.clock = clock;
    }

    @Transactional(readOnly = true)
    public GraphVersionList list(String cursor, Integer requestedLimit) {
        if (requestedLimit != null && (requestedLimit < 1 || requestedLimit > MAX_LIMIT)) {
            throw new CustomException(ErrorCode.INVALID_REQUEST);
        }
        int limit = requestedLimit == null ? DEFAULT_LIMIT : requestedLimit;
        Long before = decodeCursor(cursor);
        try {
            var rows = repository.versions(before, limit + 1);
            boolean hasNext = rows.size() > limit;
            var items = hasNext ? rows.subList(0, limit) : rows;
            String next = hasNext ? encodeCursor(items.get(limit - 1).sequence()) : null;
            String activeId = versions.active().map(GraphVersionRecord::id).orElse(null);
            return new GraphVersionList(activeId, items, repository.activations(), next);
        } catch (DataAccessException exception) {
            throw new CustomException(ErrorCode.SOURCE_UNAVAILABLE, exception);
        }
    }

    /** The cursor is the last returned sequence; versions are immutable rows ordered by sequence, so it stays valid. */
    private static Long decodeCursor(String cursor) {
        if (cursor == null) return null;
        try {
            String raw = new String(Base64.getUrlDecoder().decode(cursor), StandardCharsets.UTF_8);
            if (!raw.matches(CURSOR_PREFIX + "[1-9][0-9]{0,17}")) throw new IllegalArgumentException();
            return Long.valueOf(raw.substring(CURSOR_PREFIX.length()));
        } catch (IllegalArgumentException exception) {
            throw new CustomException(ErrorCode.INVALID_CURSOR, exception);
        }
    }

    private static String encodeCursor(long sequence) {
        return Base64.getUrlEncoder().withoutPadding()
                .encodeToString((CURSOR_PREFIX + sequence).getBytes(StandardCharsets.UTF_8));
    }

    @Transactional
    public ActivateResponse activate(String versionId, GraphVersionActivateRequest request, String idempotencyKey,
            AdminPrincipal admin, String requestId) {
        validateKey(idempotencyKey);
        String reason = request.reason().strip();
        if (!AuditReasonPolicy.safeMemberReason(reason)) {
            throw new CustomException(ErrorCode.INVALID_REQUEST);
        }
        String path = "/api/v1/admin/graph/versions/" + versionId + "/activate";
        String expected = request.expectedActiveVersionId();
        String requestHash = Canonical.sha256(versionId + "\n" + expected + "\n" + reason);
        Instant now = clock.instant();
        try {
            boolean claimed = repository.claimIdempotency(UUID.randomUUID().toString(), admin.adminId(), path,
                    idempotencyKey, versionId, requestHash, now);
            var idempotency = repository.findIdempotencyForUpdate(admin.adminId(), path, idempotencyKey)
                    .orElseThrow(() -> new IllegalStateException("Claimed idempotency record is missing"));
            if (!idempotency.requestHash().equals(requestHash)) {
                throw new CustomException(ErrorCode.IDEMPOTENCY_CONFLICT);
            }
            if (!claimed) {
                if (!"completed".equals(idempotency.status()) || idempotency.responseBody() == null) {
                    throw new CustomException(ErrorCode.SOURCE_UNAVAILABLE, true);
                }
                return mapper.readValue(idempotency.responseBody(), ActivateResponse.class);
            }

            var version = versions.find(versionId)
                    .orElseThrow(() -> new CustomException(ErrorCode.RESOURCE_NOT_FOUND));
            snapshots.load(version);
            var activation = versions.activateByAdmin(versionId, expected, admin.adminId(), admin.email(), reason, now);
            audit.recordGraphActivation(admin.adminId(), admin.email(), versionId, activation.previousVersionId(),
                    activation.pointerChanged(), reason, requestId, now);
            ActivateResponse result = new ActivateResponse(versionId, activation.previousVersionId(),
                    !activation.pointerChanged());
            repository.completeIdempotency(idempotency.id(), mapper.writeValueAsString(result));
            return result;
        } catch (CustomException exception) {
            throw exception;
        } catch (DataAccessException exception) {
            throw new CustomException(ErrorCode.SOURCE_UNAVAILABLE, exception);
        } catch (Exception exception) {
            throw new IllegalStateException("Unable to persist graph version activation", exception);
        }
    }

    private static void validateKey(String key) {
        if (key == null || key.isBlank() || key.length() > 200 || key.chars().anyMatch(Character::isISOControl)) {
            throw new CustomException(ErrorCode.INVALID_REQUEST);
        }
    }
}
