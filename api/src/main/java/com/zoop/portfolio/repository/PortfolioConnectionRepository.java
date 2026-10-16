package com.zoop.portfolio.repository;

import java.util.Optional;

public interface PortfolioConnectionRepository {
    boolean lockMember(String memberId);

    Optional<PortfolioConnectionRow> findConnection(String memberId);

    Optional<PortfolioConnectionRow> findConnection(String memberId, String connectionId);

    Optional<PortfolioIdempotencyRow> findIdempotency(String memberId, String idempotencyKey);

    void saveConnection(String memberId, PortfolioConnectionRow connection);

    void saveIdempotency(String memberId, String idempotencyKey, PortfolioIdempotencyRow record);

    boolean deleteConnection(String memberId, String connectionId);
}
