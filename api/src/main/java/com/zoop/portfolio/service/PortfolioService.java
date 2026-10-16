package com.zoop.portfolio.service;

import java.time.Clock;
import java.math.BigDecimal;
import java.util.List;
import java.util.UUID;

import com.zoop.auth.service.MemberSessionService.MemberPrincipal;
import com.zoop.common.exception.CustomException;
import com.zoop.common.exception.ErrorCode;
import com.zoop.common.response.Metadata;
import com.zoop.portfolio.dto.ConnectionInfo;
import com.zoop.portfolio.dto.ConnectionResponse;
import com.zoop.portfolio.dto.HoldingOut;
import com.zoop.portfolio.dto.MockPortfolioListResponse;
import com.zoop.portfolio.dto.MockPortfolioOption;
import com.zoop.portfolio.dto.MockProfileResponse;
import com.zoop.portfolio.dto.PortfolioResponse;
import com.zoop.portfolio.dto.PortfolioValuation;
import com.zoop.portfolio.model.MockPortfolio;
import com.zoop.portfolio.repository.PortfolioConnectionRepository;
import com.zoop.portfolio.repository.PortfolioConnectionRow;
import com.zoop.portfolio.repository.PortfolioIdempotencyRow;
import org.springframework.dao.DataAccessException;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

@Service
public class PortfolioService {
    private final MockPortfolioCatalog catalog;
    private final PortfolioConnectionRepository repository;
    private final Clock clock;

    public PortfolioService(MockPortfolioCatalog catalog, PortfolioConnectionRepository repository, Clock clock) {
        this.catalog = catalog;
        this.repository = repository;
        this.clock = clock;
    }

    @Transactional(readOnly = true)
    public MockPortfolioListResponse listProfiles(String cursor, Integer limit, String requestId) {
        var page = catalog.page(cursor, limit);
        var items = page.items().stream().map(profile -> new MockPortfolioOption(profile.id(), profile.label(),
                profile.accountId(), profile.holdings().size())).toList();
        return new MockPortfolioListResponse(items, metadata(requestId), page.nextCursor());
    }

    @Transactional(readOnly = true)
    public MockProfileResponse getProfile(String id, String requestId) {
        MockPortfolio profile = catalog.find(id).orElseThrow(() -> new CustomException(ErrorCode.RESOURCE_NOT_FOUND));
        return new MockProfileResponse(profile.id(), profile.label(), profile.accountId(), profile.cash(), profile.asOf(),
                profile.holdings().stream().map(com.zoop.portfolio.dto.MockHoldingOut::from).toList(), metadata(requestId));
    }

    @Transactional
    public ConnectionResponse connect(MemberPrincipal member, String mockPortfolioId,
            String idempotencyKey, String requestId) {
        if (mockPortfolioId == null || mockPortfolioId.isBlank() || idempotencyKey == null || idempotencyKey.isBlank()) {
            throw new CustomException(ErrorCode.INVALID_REQUEST);
        }
        MockPortfolio profile = catalog.find(mockPortfolioId)
                .orElseThrow(() -> new CustomException(ErrorCode.RESOURCE_NOT_FOUND));
        try {
            if (!repository.lockMember(member.memberId())) throw new CustomException(ErrorCode.RESOURCE_NOT_FOUND);
            var previous = repository.findIdempotency(member.memberId(), idempotencyKey);
            if (previous.isPresent()) {
                PortfolioIdempotencyRow record = previous.get();
                if (!record.mockPortfolioId().equals(mockPortfolioId)) {
                    throw new CustomException(ErrorCode.IDEMPOTENCY_CONFLICT);
                }
                return connectionResponse(record.connectionId(), profile, record.connectedAt(), requestId);
            }

            var existing = repository.findConnection(member.memberId());
            PortfolioConnectionRow connection;
            if (existing.isPresent() && existing.get().mockPortfolioId().equals(mockPortfolioId)) {
                connection = existing.get();
            } else {
                connection = new PortfolioConnectionRow(UUID.randomUUID().toString(), mockPortfolioId, clock.instant());
                repository.saveConnection(member.memberId(), connection);
            }
            var idempotency = new PortfolioIdempotencyRow(mockPortfolioId, connection.connectionId(), connection.connectedAt());
            repository.saveIdempotency(member.memberId(), idempotencyKey, idempotency);
            return connectionResponse(connection.connectionId(), profile, connection.connectedAt(), requestId);
        } catch (CustomException exception) {
            throw exception;
        } catch (DataAccessException exception) {
            throw new CustomException(ErrorCode.SOURCE_UNAVAILABLE, exception);
        }
    }

    @Transactional
    public void disconnect(MemberPrincipal member, String connectionId) {
        if (connectionId == null || connectionId.isBlank()) throw new CustomException(ErrorCode.INVALID_REQUEST);
        try {
            if (!repository.lockMember(member.memberId())) throw new CustomException(ErrorCode.RESOURCE_NOT_FOUND);
            if (repository.findConnection(member.memberId(), connectionId).isEmpty()
                    || !repository.deleteConnection(member.memberId(), connectionId)) {
                throw new CustomException(ErrorCode.RESOURCE_NOT_FOUND);
            }
        } catch (CustomException exception) {
            throw exception;
        } catch (DataAccessException exception) {
            throw new CustomException(ErrorCode.SOURCE_UNAVAILABLE, exception);
        }
    }

    @Transactional(readOnly = true)
    public PortfolioResponse getMyPortfolio(MemberPrincipal member, String requestId) {
        try {
            var connection = repository.findConnection(member.memberId());
            if (connection.isEmpty()) {
                return new PortfolioResponse(false, null, List.of(), null, null, metadata(requestId));
            }
            PortfolioConnectionRow row = connection.get();
            MockPortfolio profile = catalog.find(row.mockPortfolioId())
                    .orElseThrow(() -> new CustomException(ErrorCode.SOURCE_UNAVAILABLE));
            var connectionInfo = connectionInfo(row, profile);
            var holdings = profile.holdings().stream().map(HoldingOut::from).toList();
            PortfolioValuation valuation = profile.holdings().isEmpty()
                    ? new PortfolioValuation(clock.instant(), null, BigDecimal.ZERO, "available", null, null)
                    : new PortfolioValuation(clock.instant(), null, null, "unavailable", "missing_price",
                            "모의 보유수량은 고정값이며 현재 평가가격은 제공되지 않습니다.");
            return new PortfolioResponse(true, connectionInfo, holdings, profile.asOf(), valuation, metadata(requestId));
        } catch (CustomException exception) {
            throw exception;
        } catch (DataAccessException exception) {
            throw new CustomException(ErrorCode.SOURCE_UNAVAILABLE, exception);
        }
    }

    private ConnectionResponse connectionResponse(String id, MockPortfolio profile,
            java.time.Instant connectedAt, String requestId) {
        return new ConnectionResponse(id, profile.id(), profile.label(), connectedAt, profile.accountId(),
                profile.cash(), "connected", profile.holdings().size(), metadata(requestId));
    }

    private ConnectionInfo connectionInfo(PortfolioConnectionRow row, MockPortfolio profile) {
        return new ConnectionInfo(row.connectionId(), profile.id(), profile.label(), row.connectedAt(),
                profile.accountId(), profile.cash(), "connected");
    }

    private Metadata metadata(String requestId) {
        return new Metadata("zoop", clock.instant(), null, requestId, false, List.of());
    }
}
