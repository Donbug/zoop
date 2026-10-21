package com.zoop.admin.graph;

import java.nio.charset.StandardCharsets;
import java.time.Clock;
import java.time.Instant;
import java.util.Base64;
import java.util.LinkedHashMap;
import java.util.Map;
import java.util.Set;
import java.util.TreeSet;
import java.util.UUID;
import java.util.function.Consumer;

import com.zoop.admin.audit.AuditReasonPolicy;
import com.zoop.admin.auth.repository.AdminAuditRepository;
import com.zoop.admin.auth.service.AdminPrincipal;
import com.zoop.admin.graph.GraphVersionAdminResponse.ActivateResponse;
import com.zoop.admin.graph.GraphVersionAdminResponse.GraphVersionList;
import com.zoop.common.exception.CustomException;
import com.zoop.common.exception.ErrorCode;
import com.zoop.common.json.Canonical;
import com.zoop.common.json.StrictJson;
import com.zoop.document.evidence.graph.GraphEvidence;
import com.zoop.document.evidence.service.EvidenceService;
import com.zoop.graph.read.DisclosureExclusionReader;
import com.zoop.graph.read.GraphEvidenceSnapshotReader;
import com.zoop.graph.read.GraphSnapshotFilter;
import com.zoop.graph.snapshot.GraphSnapshotStore;
import com.zoop.graph.snapshot.PublicGraphSnapshot;
import com.zoop.graph.version.GraphVersionRecord;
import com.zoop.graph.version.JdbcGraphVersionRepository;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.dao.DataAccessException;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;
import tools.jackson.databind.ObjectMapper;
import tools.jackson.databind.node.ObjectNode;

/**
 * Lists public graph versions and moves the public pointer for an administrator (FS059). A version is activated only
 * after its snapshot loads and verifies through the configured {@link GraphSnapshotStore} and, for an imported version, its
 * evidence passes the same current-rights gates getEvidence applies, so the pointer never moves to a version the public read
 * API would answer with 503 or withheld evidence.
 */
@Service
public class AdminGraphVersionService {
    private static final Logger log = LoggerFactory.getLogger(AdminGraphVersionService.class);
    private static final int DEFAULT_LIMIT = 50;
    private static final int MAX_LIMIT = 100;
    private static final String CURSOR_PREFIX = "gv1:";
    private static final String IMPORTED = "snapshot";
    private static final String FIXTURE_SOURCE = "fixture";

    private final JdbcAdminGraphVersionRepository repository;
    private final JdbcGraphVersionRepository versions;
    private final GraphSnapshotStore snapshots;
    private final DisclosureExclusionReader exclusions;
    private final EvidenceService evidence;
    private final AdminAuditRepository audit;
    private final ObjectMapper mapper;
    private final Clock clock;
    private final boolean allowWithoutExclusionStore;
    private final String snapshotSource;

    public AdminGraphVersionService(JdbcAdminGraphVersionRepository repository, JdbcGraphVersionRepository versions,
            GraphSnapshotStore snapshots, DisclosureExclusionReader exclusions, EvidenceService evidence,
            AdminAuditRepository audit, ObjectMapper mapper, Clock clock,
            @Value("${zoop.graph.activation.allow-without-exclusion-store:false}") boolean allowWithoutExclusionStore,
            @Value("${zoop.graph.snapshot.source:none}") String snapshotSource) {
        this.repository = repository;
        this.versions = versions;
        this.snapshots = snapshots;
        this.exclusions = exclusions;
        this.evidence = evidence;
        this.audit = audit;
        this.mapper = mapper;
        this.clock = clock;
        this.allowWithoutExclusionStore = allowWithoutExclusionStore;
        this.snapshotSource = snapshotSource;
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
        String requestHash = requestHash(versionId, expected, reason);
        Instant requestedAt = clock.instant();
        try {
            boolean claimed = repository.claimIdempotency(UUID.randomUUID().toString(), admin.adminId(), path,
                    idempotencyKey, versionId, requestHash, requestedAt);
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
            PublicGraphSnapshot snapshot = snapshots.load(version);
            var activation = versions.activateByAdmin(versionId, expected, admin.adminId(), admin.email(), reason,
                    () -> publishableNow(version, snapshot, requestId));
            audit.recordGraphActivation(admin.adminId(), admin.email(), versionId, activation.previousVersionId(),
                    activation.pointerChanged(), reason, requestId, activation.activatedAt());
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

    /**
     * Runs under the publication lock, before the pointer moves (graph read contract section 0: current rights, exclusions and
     * read readiness right before the switch). A synthetic fixture is publishable only where the snapshot source itself is
     * the local/dev fixture source: an artifact deployment can still read old fixture rows, and "[합성]" data must never become
     * its public graph. Fixtures carry no rights and no stored evidence, so only imported versions get the rights checks.
     * Without an exclusion store "nothing excluded" is unknown: refused unless the operator opted in. Returns the last check,
     * which the repository runs at the activation time: grant pins are judged at the moment the version becomes public.
     */
    private Consumer<Instant> publishableNow(GraphVersionRecord version, PublicGraphSnapshot snapshot, String requestId) {
        if (!IMPORTED.equals(version.kind())) {
            if (!FIXTURE_SOURCE.equals(snapshotSource)) {
                log.info("Graph activation refused (graphVersion={}, reason=fixture_outside_fixture_source, source={}, "
                        + "requestId={})", version.id(), snapshotSource, requestId);
                throw new CustomException(ErrorCode.INVALID_REQUEST);
            }
            return at -> { };
        }
        if (!exclusions.authoritative() && !allowWithoutExclusionStore) {
            log.info("Graph activation refused (graphVersion={}, reason=exclusion_store_unavailable, requestId={})",
                    version.id(), requestId);
            throw new CustomException(ErrorCode.SOURCE_UNAVAILABLE);
        }
        PublicGraphSnapshot visible = GraphSnapshotFilter.apply(snapshot, null, exclusions.current());
        Instant at = clock.instant();
        Map<String, GraphEvidence> found = new LinkedHashMap<>();
        Set<String> articles = new TreeSet<>();
        for (PublicGraphSnapshot.Evidence cited : visible.evidence()) {
            GraphEvidence located = GraphEvidenceSnapshotReader.locate(visible, version.id(), at, cited.evidenceId());
            if (located.span() != null) {
                found.put(cited.evidenceId(), located);
                articles.add(located.span().articleId());
            }
        }
        repository.shareLockArticles(articles);
        return evidence.prepareGraphActivation(version.id(), found, requestId);
    }

    /**
     * Canonical JSON of what the request asks for, so an explicit null and an empty string stay different bodies (a joined
     * string with a sentinel made them collide: PR #275 follow-up review).
     */
    static String requestHash(String versionId, String expectedActiveVersionId, String reason) {
        ObjectNode body = StrictJson.newObject();
        body.put("versionId", versionId);
        body.put("expectedActiveVersionId", expectedActiveVersionId);
        body.put("reason", reason);
        return Canonical.digest(body);
    }

    private static void validateKey(String key) {
        if (key == null || key.isBlank() || key.length() > 200 || key.chars().anyMatch(Character::isISOControl)) {
            throw new CustomException(ErrorCode.INVALID_REQUEST);
        }
    }
}
