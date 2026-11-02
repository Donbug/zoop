package com.zoop.graph.round;

import java.util.Optional;

/**
 * Serializes round imports across every instance that shares the database. The bridge's "an older round is never imported after
 * a newer one" guard is a read followed by the import; without this lock a second instance (a deploy overlap) could import the
 * newer round between the two and the auto-activation, which picks by commit order, would publish the older one. The artifact
 * store's file lock only serializes within one host.
 */
public interface GraphRoundImportLock {

    /** The lock when it is free, empty when another import holds it; closing the handle releases it. */
    Optional<Held> tryAcquire();

    interface Held extends AutoCloseable {
        @Override
        void close();
    }
}
