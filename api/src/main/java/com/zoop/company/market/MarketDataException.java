package com.zoop.company.market;

public class MarketDataException extends RuntimeException {
    private final boolean retryable;
    public MarketDataException(boolean retryable) { super("Market data provider request failed"); this.retryable = retryable; }
    public boolean retryable() { return retryable; }
}
