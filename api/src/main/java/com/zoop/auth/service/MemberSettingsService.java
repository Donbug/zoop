package com.zoop.auth.service;

import java.time.Clock;
import java.util.ArrayList;
import java.util.HashSet;
import java.util.List;

import tools.jackson.databind.JsonNode;
import com.zoop.auth.dto.SettingsResponse;
import com.zoop.auth.repository.MemberSettingsRepository;
import com.zoop.auth.repository.MemberSettingsRow;
import com.zoop.auth.service.MemberSessionService.MemberPrincipal;
import com.zoop.common.exception.CustomException;
import com.zoop.common.exception.ErrorCode;
import com.zoop.common.response.Metadata;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

@Service
public class MemberSettingsService {
    private final MemberSettingsRepository repository;
    private final Clock clock;

    public MemberSettingsService(MemberSettingsRepository repository, Clock clock) {
        this.repository = repository;
        this.clock = clock;
    }

    @Transactional(readOnly = true)
    public SettingsResponse get(MemberPrincipal member, String requestId) {
        var row = repository.find(member.memberId()).orElseThrow(() -> new CustomException(ErrorCode.RESOURCE_NOT_FOUND));
        return response(row, requestId);
    }

    @Transactional
    public SettingsResponse update(MemberPrincipal member, JsonNode input, String requestId) {
        var current = repository.findForUpdate(member.memberId())
                .orElseThrow(() -> new CustomException(ErrorCode.RESOURCE_NOT_FOUND));
        if (input == null || !input.isObject() || !input.has("version")
                || !input.get("version").isIntegralNumber() || !input.get("version").canConvertToLong()
                || input.get("version").longValue() < 1) {
            throw new CustomException(ErrorCode.INVALID_REQUEST);
        }
        var allowed = java.util.Set.of("version", "mode", "watchlistIds", "tutorialCompleted", "completed", "investor");
        if (!allowed.containsAll(input.propertyNames())) throw new CustomException(ErrorCode.INVALID_REQUEST);

        String mode = current.mode();
        if (input.has("mode") && !input.get("mode").isNull()) {
            var value = input.get("mode");
            if (!value.isTextual() || !(value.textValue().equals("assets") || value.textValue().equals("watchlist"))) {
                throw new CustomException(ErrorCode.INVALID_REQUEST);
            }
            mode = value.textValue();
        }
        Boolean investor = current.investor();
        if (input.has("investor")) {
            var value = input.get("investor");
            if (value.isNull()) investor = null;
            else if (value.isBoolean()) investor = value.booleanValue();
            else throw new CustomException(ErrorCode.INVALID_REQUEST);
        }
        boolean completed = booleanPatch(input, "completed", current.completed());
        boolean tutorialCompleted = booleanPatch(input, "tutorialCompleted", current.tutorialCompleted());
        List<String> watchlist = stringListPatch(input, current.watchlistIds());
        if (new HashSet<>(watchlist).size() != watchlist.size()) throw new CustomException(ErrorCode.INVALID_REQUEST);
        if (completed && (investor == null || mode == null)) {
            throw new CustomException(ErrorCode.INVALID_REQUEST);
        }

        boolean watchlistChanged = !watchlist.equals(current.watchlistIds());
        boolean unchanged = java.util.Objects.equals(mode, current.mode()) && java.util.Objects.equals(investor, current.investor())
                && completed == current.completed() && tutorialCompleted == current.tutorialCompleted()
                && !watchlistChanged;
        long requestedVersion = input.get("version").longValue();
        if (requestedVersion != current.version()) {
            if (unchanged) return response(current, requestId);
            throw new CustomException(ErrorCode.REVISION_CONFLICT);
        }
        if (unchanged) return response(current, requestId);
        if (current.version() == Long.MAX_VALUE) throw new CustomException(ErrorCode.REVISION_CONFLICT);
        if (watchlistChanged && !repository.companiesExist(watchlist)) {
            throw new CustomException(ErrorCode.RESOURCE_NOT_FOUND);
        }

        long nextVersion = current.version() + 1;
        repository.update(member.memberId(), mode, investor, completed, tutorialCompleted,
                current.version(), nextVersion);
        if (watchlistChanged) repository.replaceWatchlist(member.memberId(), watchlist);
        var updated = new MemberSettingsRow(mode, investor, completed, tutorialCompleted, nextVersion, watchlist);
        return response(updated, requestId);
    }

    private static boolean booleanPatch(JsonNode input, String field, boolean stored) {
        if (!input.has(field) || input.get(field).isNull()) return stored;
        if (!input.get(field).isBoolean()) throw new CustomException(ErrorCode.INVALID_REQUEST);
        return input.get(field).booleanValue();
    }

    private static List<String> stringListPatch(JsonNode input, List<String> stored) {
        if (!input.has("watchlistIds") || input.get("watchlistIds").isNull()) return stored;
        JsonNode value = input.get("watchlistIds");
        if (!value.isArray()) throw new CustomException(ErrorCode.INVALID_REQUEST);
        var ids = new ArrayList<String>();
        for (JsonNode id : value) {
            if (!id.isTextual() || id.textValue().isBlank()) throw new CustomException(ErrorCode.INVALID_REQUEST);
            ids.add(id.textValue());
        }
        return List.copyOf(ids);
    }

    private SettingsResponse response(MemberSettingsRow row, String requestId) {
        return new SettingsResponse(row.mode(), row.watchlistIds(), row.tutorialCompleted(), row.completed(),
                row.investor(), row.version(), new Metadata("zoop", clock.instant(), null, requestId, false, List.of()));
    }
}
