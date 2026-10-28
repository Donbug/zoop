package com.zoop.briefing.query;

import java.time.Clock;
import java.time.DateTimeException;
import java.time.Instant;
import java.time.LocalDate;
import java.time.LocalTime;
import java.time.ZoneId;
import java.util.List;

import com.zoop.briefing.storage.BriefingChange;
import com.zoop.briefing.storage.BriefingRound;
import com.zoop.briefing.storage.BriefingRoundRepository;
import com.zoop.briefing.replay.BriefingReplayReadPolicy;
import com.zoop.graph.read.PublicGraphReader;
import com.zoop.graph.snapshot.GraphSnapshotUnavailableException;
import com.zoop.graph.version.BriefingGraphUnavailableException;
import com.zoop.common.exception.CustomException;
import com.zoop.common.exception.ErrorCode;
import org.springframework.dao.DataAccessException;
import org.springframework.stereotype.Service;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.transaction.annotation.Isolation;
import org.springframework.transaction.annotation.Transactional;
import tools.jackson.databind.json.JsonMapper;
import tools.jackson.databind.JsonNode;
import tools.jackson.databind.node.ObjectNode;
import tools.jackson.databind.node.ArrayNode;

/** Public reads only restore a preserved original; neither a source nor a model is called here. */
@Service
public class BriefingQueryService {
    private static final ZoneId KST = ZoneId.of("Asia/Seoul");
    private static final LocalTime MORNING = LocalTime.of(9, 20);
    private static final LocalTime EVENING = LocalTime.of(17, 30);
    private final BriefingRoundRepository repository;
    private final Clock clock;
    private final BriefingContentAccess access;
    private final BriefingReplayReadPolicy replay;
    private final PublicGraphReader graphSnapshots;
    private final JsonMapper mapper = JsonMapper.builder().build();

    public BriefingQueryService(BriefingRoundRepository repository, Clock clock, BriefingContentAccess access) {
        this(repository, clock, access, BriefingReplayReadPolicy.disabled());
    }

    public BriefingQueryService(BriefingRoundRepository repository, Clock clock, BriefingContentAccess access,
            BriefingReplayReadPolicy replay) {
        this(repository, clock, access, replay, null);
    }

    @Autowired
    public BriefingQueryService(BriefingRoundRepository repository, Clock clock, BriefingContentAccess access,
            BriefingReplayReadPolicy replay, PublicGraphReader graphSnapshots) {
        this.repository = repository;
        this.clock = clock;
        this.access = access;
        this.replay = replay;
        this.graphSnapshots = graphSnapshots;
    }

    @Transactional(readOnly = true, isolation = Isolation.REPEATABLE_READ, timeout = 5)
    public ObjectNode get(LocalDate date, String edition, String requestId) {
        validateEdition(edition);
        try {
            BriefingRound row = date != null && edition != null
                    ? repository.find(date, edition).orElse(null)
                    : repository.latest(date, edition).orElse(null);
            if (row == null) {
                var target = target(date, edition);
                return empty(target.date(), target.edition(), null, requestId, "not_ready", List.of());
            }
            List<BriefingChange> changes = repository.changes(row.id());
            if (row.publishedAt() == null) {
                String status = switch (row.status()) {
                    case "generating", "verifying" -> "generating";
                    case "failed" -> "failed";
                    default -> "not_ready";
                };
                return empty(row.date(), row.edition(), row, requestId, status, List.of());
            }
            if (row.status().equals("suspended")) {
                return empty(row.date(), row.edition(), row, requestId, "suspended", changes);
            }
            requireReadable(row, requestId);
            return restore(row, changes, requestId);
        } catch (DataAccessException | IllegalArgumentException | DateTimeException error) {
            throw new CustomException(ErrorCode.SOURCE_UNAVAILABLE);
        }
    }

    /** Read-only recap of the exact prior publication fixed by this round. Never selects a newer fallback. */
    @Transactional(readOnly = true, isolation = Isolation.REPEATABLE_READ, timeout = 5)
    public ObjectNode recap(String id, String requestId) {
        if (id == null || id.isBlank() || id.length() > 256) throw new CustomException(ErrorCode.INVALID_REQUEST);
        try {
            var row = repository.findById(id).orElseThrow(() -> new CustomException(ErrorCode.RESOURCE_NOT_FOUND));
            var out = mapper.createObjectNode().put("roundId", id).putNull("graphVersion").putNull("dataAsOf");
            out.putNull("previous");
            if (row.publishedAt() == null || !"published".equals(row.status())) {
                return recapState(out, "not_applicable", "not_published", "정상 발행된 회차에서만 이전 내용을 복기합니다.");
            }
            requireReadable(row, requestId);
            validateSnapshot(row);
            out.put("graphVersion", row.graphVersion()).put("dataAsOf", row.windowTo().toString());
            if (!row.payload().path("items").isEmpty() || !"no_issues_in_window".equals(row.payload().path("emptyReason").asString())) {
                return recapState(out, "not_applicable", "has_new_issues", "이번 회차의 핵심 이슈를 확인해 주세요.");
            }
            if (repository.changes(id).stream().anyMatch(change -> "correction".equals(change.kind()))) {
                return recapState(out, "unavailable", "current_corrected", "이번 회차의 정정 내용을 먼저 확인해 주세요.");
            }
            boolean evening = "evening".equals(row.edition());
            JsonNode reference = evening ? row.comparisonSnapshot() : row.publicSnapshot().path("previousComparison");
            if (reference == null || !"available".equals(reference.path("status").asString())) {
                return recapState(out, "unavailable", "previous_not_recorded", "발행 시 고정한 이전 회차가 없어 복기할 수 없습니다.");
            }
            String prefix = evening ? "morning" : "previous";
            var previous = repository.findById(reference.path(prefix + "RoundId").asString()).orElse(null);
            if (previous == null || previous.publishedAt() == null || !"published".equals(previous.status())) {
                return recapState(out, "unavailable", "previous_not_available", "고정된 이전 회차를 현재 제공할 수 없습니다.");
            }
            if (id.equals(previous.id()) || !previous.windowTo().isBefore(row.windowTo())
                    || (row.windowFrom() != null && previous.windowTo().isAfter(row.windowFrom()))
                    || !previous.windowTo().equals(Instant.parse(reference.path(prefix + "DataAsOf").asString()))
                    || (reference.path(prefix + "PublishedAt").isString()
                        && !previous.publishedAt().equals(Instant.parse(reference.path(prefix + "PublishedAt").asString())))
                    || (evening && (!previous.date().equals(row.date()) || !"morning".equals(previous.edition())))
                    || (!evening && reference.has("previousDate")
                        && (!previous.date().toString().equals(reference.path("previousDate").asString())
                            || !previous.edition().equals(reference.path("previousEdition").asString())))) {
                return recapState(out, "unavailable", "previous_basis_changed", "이전 회차의 고정 시점이 일치하지 않아 복기를 제공하지 않습니다.");
            }
            requireReadable(previous, requestId);
            var changes = repository.changes(previous.id());
            if (changes.stream().anyMatch(change -> "correction".equals(change.kind()))) {
                return recapState(out, "unavailable", "previous_corrected", "이전 회차에 정정이 있어 과거 문안을 다시 강조하지 않습니다.");
            }
            var restored = restore(previous, changes, requestId);
            if (restored.path("items").isEmpty()) {
                return recapState(out, "unavailable", "previous_has_no_issues", "고정된 이전 회차에도 복기할 핵심 이슈가 없습니다.");
            }
            out.set("previous", restored);
            return recapState(out, "available", null, "확인한 자료 범위에서 선정 기준을 충족한 새 핵심 이슈가 없습니다. 이전 발행 내용을 복기하며 이번 회차의 새 전망이나 재평가를 뜻하지 않습니다.");
        } catch (DataAccessException | IllegalArgumentException | DateTimeException error) {
            throw new CustomException(ErrorCode.SOURCE_UNAVAILABLE);
        }
    }

    private ObjectNode recapState(ObjectNode out, String status, String reason, String message) {
        return out.put("status", status).put("reason", reason).put("message", message);
    }

    @Transactional(readOnly = true, isolation = Isolation.REPEATABLE_READ, timeout = 5)
    public ObjectNode history(String cursor, Integer requestedLimit) {
        int limit = requestedLimit == null ? 20 : requestedLimit;
        if (limit < 1 || limit > 100) throw new CustomException(ErrorCode.INVALID_REQUEST);
        var key = BriefingCursor.decode(cursor, limit);
        try {
            var rows = repository.history(key == null ? null : key.scheduledAt(), key == null ? null : key.id(), limit + 1);
            var out = mapper.createObjectNode();
            var items = out.putArray("items");
            for (var row : rows.subList(0, Math.min(limit, rows.size()))) {
                if (!List.of("published", "suspended").contains(row.status()) || row.publishedAt() == null) unavailable();
                items.addObject().put("id", row.id()).put("date", row.date().toString()).put("edition", row.edition())
                        .put("status", row.status()).put("publishedAt", row.publishedAt().toString());
            }
            out.put("nextCursor", rows.size() > limit ? BriefingCursor.encode(rows.get(limit - 1), limit) : null);
            return out;
        } catch (DataAccessException error) {
            throw new CustomException(ErrorCode.SOURCE_UNAVAILABLE);
        }
    }

    @Transactional(readOnly = true, isolation = Isolation.REPEATABLE_READ, timeout = 5)
    public ObjectNode graphBasis(String id, String requestId) {
        if (id == null || id.isBlank() || id.length() > 256) throw new CustomException(ErrorCode.INVALID_REQUEST);
        try {
            var row = repository.findById(id).orElseThrow(() -> new CustomException(ErrorCode.RESOURCE_NOT_FOUND));
            var changes = repository.changes(row.id());
            var out = mapper.createObjectNode().put("roundId", row.id()).put("date", row.date().toString())
                    .put("edition", row.edition()).put("publishedAt", row.publishedAt() == null ? null : row.publishedAt().toString());
            out.put("dataAsOf", row.publishedAt() == null ? null : row.windowTo().toString());
            out.put("graphVersion", row.publishedAt() == null ? null : row.graphVersion());
            out.putArray("keyIssueIds");
            out.putArray("companyIds");
            out.putNull("unavailableReason").putNull("graphOrigin").putNull("reconstructedAt");
            out.put("correctionCount", changes.stream().filter(change -> "correction".equals(change.kind())).count());
            if (row.publishedAt() == null) {
                out.put("status", "not_published").put("message", "아직 발행되지 않은 회차입니다.").putNull("reason");
            } else if ("suspended".equals(row.status())) {
                var suspension = suspension(changes);
                out.put("status", "suspended").put("message", "이 회차의 제공을 중단했습니다.")
                        .put("reason", suspension == null ? null : suspension.reason());
            } else {
                requireReadable(row, requestId);
                if (graphSnapshots == null) {
                    graphUnavailable(out, row.graphVersion() == null ? "snapshot_not_recorded" : "snapshot_unavailable");
                } else {
                    try {
                        var pinned = graphSnapshots.read(row.id(), row.graphVersion(), row.windowTo(), requestId);
                        var basis = pinned.selected().briefing();
                        if (basis == null || !row.id().equals(basis.roundId())) unavailable();
                        basis.keyIssueIds().forEach(out.withArray("keyIssueIds")::add);
                        basis.companyIds().forEach(out.withArray("companyIds")::add);
                        out.put("graphVersion", basis.graphVersion());
                        out.put("status", "available").putNull("reason");
                        if (basis.reconstruction() != null) {
                            out.put("graphOrigin", "reconstructed").put("reconstructedAt", basis.reconstruction().createdAt().toString());
                            out.put("message", "발행 당시 저장본이 아니라, 회차 마감 이전에 발행된 저장 자료로 나중에 재구성한 그래프입니다. 당시 수집·본문 버전의 동일성을 보장하지 않습니다.");
                        } else {
                            out.put("graphOrigin", "publication_snapshot").putNull("message");
                        }
                    } catch (BriefingGraphUnavailableException error) {
                        graphUnavailable(out, error.reason());
                    } catch (GraphSnapshotUnavailableException error) {
                        graphUnavailable(out, "snapshot_unavailable");
                    }
                }
            }
            return out;
        } catch (DataAccessException | IllegalArgumentException | DateTimeException error) {
            throw new CustomException(ErrorCode.SOURCE_UNAVAILABLE);
        }
    }

    /** Restore only the selected item's preserved detail after the same current authority check as the round. */
    @Transactional(readOnly = true, isolation = Isolation.REPEATABLE_READ, timeout = 5)
    public ObjectNode getItem(String roundId, String eventId, String requestId) {
        if (roundId == null || roundId.isBlank() || roundId.length() > 256
                || eventId == null || eventId.isBlank() || eventId.length() > 256) {
            throw new CustomException(ErrorCode.INVALID_REQUEST);
        }
        try {
            var row = repository.findById(roundId).orElseThrow(() -> new CustomException(ErrorCode.RESOURCE_NOT_FOUND));
            requireReadable(row, requestId);
            validateSnapshot(row);
            JsonNode selected = null;
            for (JsonNode item : row.payload().path("items")) {
                if (eventId.equals(item.path("eventId").asString())) selected = item;
            }
            if (selected == null) throw new CustomException(ErrorCode.RESOURCE_NOT_FOUND);
            JsonNode detail = row.publicSnapshot().path("itemDetails").path(eventId);
            if (detail.isMissingNode() || detail.isNull()) throw new CustomException(ErrorCode.RESOURCE_NOT_FOUND);
            BriefingItemDetailValidator.validate(row, selected, detail, repository);
            ObjectNode out = (ObjectNode) detail.deepCopy();
            ((ObjectNode) out.path("metadata")).put("requestId", requestId);
            return out;
        } catch (DataAccessException | IllegalArgumentException | DateTimeException | com.zoop.common.json.StrictJson.Malformed error) {
            throw new CustomException(ErrorCode.SOURCE_UNAVAILABLE);
        }
    }

    /** Read authority and immutable selection basis shared by the S3 impact endpoint; no item-detail snapshot required. */
    @Transactional(readOnly = true, isolation = Isolation.REPEATABLE_READ, timeout = 5)
    public BriefingRound impactBasis(String roundId, String eventId, String requestId) {
        if (roundId == null || roundId.isBlank() || roundId.length() > 256
                || eventId == null || eventId.isBlank() || eventId.length() > 256)
            throw new CustomException(ErrorCode.INVALID_REQUEST);
        try {
            var row = repository.findById(roundId).orElseThrow(() -> new CustomException(ErrorCode.RESOURCE_NOT_FOUND));
            if (row.publishedAt() == null) throw new CustomException(ErrorCode.RESOURCE_NOT_FOUND);
            requireReadable(row, requestId);
            validateSnapshot(row);
            int count = 0;
            for (JsonNode item : row.payload().path("items"))
                if (eventId.equals(item.path("eventId").asString())) count++;
            if (count != 1) throw new CustomException(ErrorCode.RESOURCE_NOT_FOUND);
            return row;
        } catch (DataAccessException | IllegalArgumentException | DateTimeException | com.zoop.common.json.StrictJson.Malformed error) {
            throw new CustomException(ErrorCode.SOURCE_UNAVAILABLE);
        }
    }

    private ObjectNode restore(BriefingRound row, List<BriefingChange> changes, String requestId) {
        validateSnapshot(row);
        var payload = row.payload();
        var out = mapper.createObjectNode();
        for (String field : List.of("id", "date", "edition", "scheduledAt", "generatedAt", "dataWindow", "graphVersion",
                "items", "references", "emptyReason", "outlook", "metadata")) {
            out.set(field, payload.get(field).deepCopy());
        }
        out.put("status", "published").put("publishedAt", row.publishedAt().toString());
        out.set("dataAsOf", payload.get("dataWindow").get("end").deepCopy());
        out.set("marketSummary", row.publicSnapshot().get("marketSummary").deepCopy());
        JsonNode editionReview = row.publicSnapshot().get("editionReview");
        if (editionReview != null) out.set("editionReview", editionReview.deepCopy());
        JsonNode aiPrice = row.publicSnapshot().get("aiPriceOutlooks");
        if (aiPrice != null) out.set("aiPriceOutlooks", aiPrice.deepCopy());
        JsonNode priceContext = row.publicSnapshot().get("companyPriceContext");
        if (priceContext != null) out.set("companyPriceContext", priceContext.deepCopy());
        JsonNode judgment = row.publicSnapshot().get("judgmentUpdate");
        if (judgment != null) out.set("judgmentUpdate", judgment.deepCopy());
        JsonNode companyOutlooks = row.publicSnapshot().get("companyOutlooks");
        if (companyOutlooks != null) out.set("companyOutlooks", companyOutlooks.deepCopy());
        var market = payload.get("marketVariables");
        out.set("marketVariables", market.isNull() ? unavailableSection("발행 당시 시장 지표가 저장되지 않았습니다.") : publicMarketVariables(market));
        out.set("sinceMorning", row.comparisonSnapshot() == null ? mapper.nullNode() : row.comparisonSnapshot().deepCopy());
        JsonNode previous = row.publicSnapshot().get("previousComparison");
        out.set("previousComparison", previous == null ? mapper.nullNode() : previous.deepCopy());
        var corrections = out.putArray("corrections");
        for (var change : changes) {
            if (!"correction".equals(change.kind())) continue;
            if (change.corrected() == null || change.reason() == null || change.createdAt() == null) unavailable();
            corrections.addObject().put("id", change.id()).put("eventId", change.eventId()).put("original", change.original())
                    .put("corrected", change.corrected()).put("reason", change.reason()).put("createdAt", change.createdAt().toString());
        }
        out.putNull("notice");
        if (row.publicSnapshot().has("continuity")) out.set("continuity", continuity(row, requestId));
        ((ObjectNode) out.get("metadata")).put("requestId", requestId);
        return out;
    }

    private JsonNode continuity(BriefingRound row, String requestId) {
        ObjectNode value = (ObjectNode) row.publicSnapshot().path("continuity").deepCopy();
        if (!row.id().equals(value.path("roundId").asString()) || !row.windowTo().equals(Instant.parse(value.path("cutoff").asString()))) unavailable();
        JsonNode recap=value.path("recap");
        if ("available".equals(recap.path("status").asString())) {
            BriefingRound previous=repository.findById(recap.path("previousRoundId").asString()).orElse(null);
            boolean valid=previous!=null && previous.publishedAt()!=null && "published".equals(previous.status())
                    && previous.windowTo().isBefore(row.windowTo()) && (row.windowFrom()==null || !previous.windowTo().isAfter(row.windowFrom()))
                    && previous.windowTo().equals(Instant.parse(recap.path("dataAsOf").asString()))
                    && previous.payload().path("items").equals(recap.path("items"))
                    && repository.changes(previous.id()).stream().noneMatch(c->"correction".equals(c.kind()));
            if (valid) { requireReadable(previous,requestId); validateSnapshot(previous); }
            else {
                ObjectNode old=value.withObject("recap");old.put("status","unavailable").put("message","고정한 이전 발행본이 변경·정정·중단되어 복기를 제공하지 않습니다.");old.putArray("items");
                ArrayNode conditions=mapper.createArrayNode();
                for(JsonNode condition:value.path("watchConditions")) if(!"previous_condition".equals(condition.path("kind").asString()))conditions.add(condition);
                value.set("watchConditions",conditions);
            }
        }
        return value;
    }

    /** Contract projection only: legacy bank daily references were stored under the old close enum. */
    private static JsonNode publicMarketVariables(JsonNode stored) {
        JsonNode copy = stored.deepCopy();
        if (!"available".equals(copy.path("status").asString())) return copy;
        for (JsonNode indicator : copy.path("indicators")) {
            JsonNode source = indicator.path("source");
            if ("usdkrw".equals(indicator.path("id").asString())
                    && "close".equals(indicator.path("valueKind").asString())
                    && indicator.path("observedAt").isNull()
                    && "naver".equals(source.path("provider").asString())
                    && "FX_USDKRW".equals(source.path("symbol").asString())
                    && source.path("url").asString("").startsWith("https://api.stock.naver.com/marketindex/exchange/FX_USDKRW/prices?")) {
                ((ObjectNode) indicator).put("valueKind", "reference");
            }
        }
        return copy;
    }

    private ObjectNode empty(LocalDate date, String edition, BriefingRound row, String requestId, String status,
            List<BriefingChange> changes) {
        Instant scheduled = row == null ? date.atTime(time(edition)).atZone(KST).toInstant() : row.scheduledAt();
        var out = mapper.createObjectNode().put("id", row == null ? "brf-" + date + "-" + edition : row.id())
                .put("date", date.toString()).put("edition", edition).put("status", status).put("scheduledAt", scheduled.toString());
        out.put("publishedAt", row == null || row.publishedAt() == null ? null : row.publishedAt().toString());
        out.putNull("generatedAt").putNull("dataAsOf").putNull("graphVersion").putNull("outlook").putNull("emptyReason");
        if (row == null) out.putNull("dataWindow");
        else out.putObject("dataWindow").put("start", row.windowFrom() == null ? null : row.windowFrom().toString())
                .put("end", row.windowTo().toString()).put("openStart", row.openStart());
        out.putArray("items"); out.putArray("corrections");
        var references = out.putObject("references");
        references.putArray("eventIds"); references.putArray("evidenceIds"); references.putArray("companyIds");
        out.set("marketSummary", unavailableSection("이 회차의 공개 내용을 제공하지 않습니다."));
        out.set("marketVariables", unavailableSection("이 회차의 공개 내용을 제공하지 않습니다."));
        out.putNull("sinceMorning");
        out.putNull("previousComparison");
        var metadata = out.putObject("metadata");
        metadata.put("source", "zoop-briefing").put("asOf", clock.instant().toString()).putNull("graphVersion")
                .put("requestId", requestId).put("partial", false);
        metadata.putArray("failures");
        if (row != null && row.publishedAt() == null && BriefingReplayReadPolicy.marked(row) && replay.permits(row)
                && "publication_clock_simulation".equals(row.publicSnapshot().path("replay").path("scope").asString())) {
            metadata.put("source", "zoop-briefing-publication-clock-simulation").put("partial", true);
            JsonNode continuity = row.publicSnapshot().path("continuity");
            if (List.of("coverage_limited", "validation_failed").contains(continuity.path("mode").asString())
                    && continuity.path("references").isEmpty() && !"available".equals(continuity.path("recap").path("status").asString())) {
                out.set("continuity", continuity.deepCopy()); out.put("dataAsOf", row.windowTo().toString());
            }
            metadata.withArray("failures").addObject().put("section", "sourceCoverage").put("code", "SIMULATION_HELD")
                    .put("message", "과거 발행시각 시뮬레이션에서 입력·선정·검증이 완료되지 않아 발행하지 않은 회차입니다.")
                    .put("retryable", false).putNull("asOf");
        }
        metadata.putObject("schedule").put("morning", "09:20").put("evening", "17:30").put("confirmed", true);
        metadata.putObject("selection").put("basis", "market").putNull("reason");
        String message = switch (status) {
            case "generating" -> "브리핑을 만드는 중입니다.";
            case "failed" -> "브리핑을 준비하지 못했습니다.";
            case "suspended" -> "이 회차의 제공을 중단했습니다.";
            default -> "아직 발행 전입니다.";
        };
        var suspension = "suspended".equals(status) ? suspension(changes) : null;
        out.putObject("notice").put("kind", status.equals("generating") ? "not_ready" : status).put("message", message)
                .put("reason", suspension == null ? null : suspension.reason())
                .put("at", suspension == null || suspension.createdAt() == null ? null : suspension.createdAt().toString());
        return out;
    }

    private void requireReadable(BriefingRound row, String requestId) {
        if (BriefingReplayReadPolicy.marked(row) && !replay.permits(row)) unavailable();
        if (!"published".equals(row.status()) || !access.mayRead(row, requestId)) unavailable();
    }

    private static void graphUnavailable(ObjectNode out, String reason) {
        String message = switch (reason) {
            case "snapshot_not_recorded" -> "이 과거 회차에는 발행 당시 그래프 저장본이 없습니다. 현재 그래프는 별도로 볼 수 있습니다.";
            case "briefing_targets_unavailable" -> "이 회차의 핵심 이슈·관련 기업을 저장된 그래프에서 확인할 수 없습니다.";
            default -> "발행 당시 그래프 저장본을 불러올 수 없습니다. 현재 그래프로 대체하지 않습니다.";
        };
        out.put("status", "unavailable").put("unavailableReason", reason).put("message", message).putNull("reason");
    }

    private void validateSnapshot(BriefingRound row) {
        BriefingSnapshotValidator.validate(row, BriefingReplayReadPolicy.marked(row) && replay.permits(row));
    }

    private BriefingChange suspension(List<BriefingChange> changes) {
        BriefingChange latest = null;
        for (var change : changes) {
            if (Boolean.TRUE.equals(change.suspended()) && (latest == null || change.id() > latest.id())) latest = change;
        }
        return latest;
    }

    private Target target(LocalDate date, String edition) {
        var now = clock.instant().atZone(KST);
        if (date == null) {
            date = now.toLocalDate();
            if (edition == null) {
                if (!now.toLocalTime().isBefore(EVENING)) edition = "evening";
                else if (!now.toLocalTime().isBefore(MORNING)) edition = "morning";
                else { edition = "evening"; date = date.minusDays(1); }
            } else if (now.toLocalTime().isBefore(time(edition))) date = date.minusDays(1);
        } else if (edition == null) {
            edition = now.toLocalDate().isAfter(date) || (now.toLocalDate().equals(date) && !now.toLocalTime().isBefore(EVENING))
                    ? "evening" : "morning";
        }
        return new Target(date, edition);
    }

    private record Target(LocalDate date, String edition) { }
    private ObjectNode unavailableSection(String reason) { return mapper.createObjectNode().put("status", "unavailable").put("reason", reason); }
    private static LocalTime time(String edition) { return edition.equals("morning") ? MORNING : EVENING; }
    private static void validateEdition(String edition) {
        if (edition != null && !List.of("morning", "evening").contains(edition)) throw new CustomException(ErrorCode.INVALID_REQUEST);
    }
    private static void unavailable() { throw new CustomException(ErrorCode.SOURCE_UNAVAILABLE); }
}
