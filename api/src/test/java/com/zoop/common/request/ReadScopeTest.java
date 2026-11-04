package com.zoop.common.request;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertThrows;

import java.util.concurrent.atomic.AtomicInteger;
import org.junit.jupiter.api.Test;

class ReadScopeTest {
    @Test
    void outsideAScopeEveryCallComputes() {
        AtomicInteger calls = new AtomicInteger();
        ReadScope.memo("k", calls::incrementAndGet);
        ReadScope.memo("k", calls::incrementAndGet);
        assertEquals(2, calls.get());
    }

    @Test
    void oneScopeKeepsTheFirstValuePerKeyUntilItCloses() {
        AtomicInteger calls = new AtomicInteger();
        try (ReadScope ignored = ReadScope.open()) {
            assertEquals(1, ReadScope.memo("k", calls::incrementAndGet));
            assertEquals(1, ReadScope.memo("k", calls::incrementAndGet));
            assertEquals(2, ReadScope.memo("other", calls::incrementAndGet));
        }
        assertEquals(3, ReadScope.memo("k", calls::incrementAndGet), "a closed scope keeps nothing");
    }

    @Test
    void aFailureIsNotKeptAndANestedComputationMayMemoOtherKeys() {
        AtomicInteger calls = new AtomicInteger();
        try (ReadScope ignored = ReadScope.open()) {
            assertThrows(IllegalStateException.class, () -> ReadScope.memo("k", () -> {
                calls.incrementAndGet();
                throw new IllegalStateException();
            }));
            assertEquals("inner+outer", ReadScope.memo("k", () -> ReadScope.memo("inner", () -> "inner") + "+outer"));
            assertEquals("inner", ReadScope.memo("inner", () -> "again"));
        }
        assertEquals(1, calls.get());
    }

    @Test
    void aNestedScopeSharesTheOuterOneAndLeavesItOpen() {
        AtomicInteger calls = new AtomicInteger();
        try (ReadScope ignored = ReadScope.open()) {
            ReadScope.memo("k", calls::incrementAndGet);
            try (ReadScope nested = ReadScope.open()) {
                ReadScope.memo("k", calls::incrementAndGet);
            }
            ReadScope.memo("k", calls::incrementAndGet);
        }
        assertEquals(1, calls.get());
    }
}
