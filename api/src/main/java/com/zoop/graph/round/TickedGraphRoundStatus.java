package com.zoop.graph.round;

import java.time.Clock;
import java.time.Instant;
import java.util.List;
import java.util.Optional;
import com.zoop.graph.round.GraphRoundTicks.Tick;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.transaction.support.TransactionOperations;

/**
 * The scheduler status of a web process that runs no scheduler itself (the public web with the admin round commands, #55 PR-P4):
 * read from the writers' heartbeats. Enabled while a writer with this process's slot calendar is alive (a writer with another
 * calendar would run rounds this process names differently, so it is logged and not counted). The last pass is the freshest live
 * writer's; the next slot comes from this process's own calendar. The heartbeats are read in a transaction of their own, so a
 * failed read never aborts the caller's (the admin overview's, a command's); when they cannot be read the status says disabled and
 * {@link #available()} false. One read serves every call within a second, so one overview sees one state.
 */
public final class TickedGraphRoundStatus implements GraphRoundStatus {
    private static final Logger log = LoggerFactory.getLogger(TickedGraphRoundStatus.class);

    private final GraphRoundTicks ticks;
    private final GraphRoundClock calendar;
    private final Clock clock;
    private final TransactionOperations ownTransaction;
    private volatile Read last;

    private record Read(Instant at, Optional<Tick> live, boolean available) {
    }

    public TickedGraphRoundStatus(GraphRoundTicks ticks, GraphRoundClock calendar, Clock clock, TransactionOperations ownTransaction) {
        this.ticks = ticks;
        this.calendar = calendar;
        this.clock = clock;
        this.ownTransaction = ownTransaction;
    }

    @Override
    public boolean enabled() {
        return live().isPresent();
    }

    @Override
    public Optional<Instant> nextSlotAt() {
        return live().isPresent() ? calendar.nextSlotAt(clock.instant()) : Optional.empty();
    }

    @Override
    public Optional<Instant> lastTickAt() {
        return live().flatMap(Tick::lastPassAt);
    }

    @Override
    public boolean available() {
        return read().available();
    }

    private Optional<Tick> live() {
        return read().live();
    }

    private Read read() {
        Instant now = clock.instant();
        Read previous = last;
        if (previous != null && !previous.at().isAfter(now) && previous.at().plusSeconds(1).isAfter(now)) return previous;
        Read fresh;
        try {
            List<Tick> all = ownTransaction.execute(status -> ticks.all());
            fresh = new Read(now, freshest(all == null ? List.of() : all), true);
        } catch (RuntimeException unavailable) {
            log.warn("graph round heartbeats unreadable ({})", unavailable.getClass().getSimpleName());
            fresh = new Read(now, Optional.empty(), false);
        }
        last = fresh;
        return fresh;
    }

    /**
     * The freshest live writer with this calendar. More than one alive is logged: a second writer breaks the single-writer rule, and
     * a writer restarted after a crash shows its old row next to the new one until the old ages out (three intervals).
     */
    private Optional<Tick> freshest(List<Tick> all) {
        String digest = calendar.digest();
        List<Tick> alive = all.stream().filter(Tick::alive).toList();
        alive.stream().filter(tick -> !digest.equals(tick.calendarDigest()))
                .forEach(tick -> log.warn("graph round: writer {} runs another slot calendar; not counted", tick.owner()));
        List<Tick> matching = alive.stream().filter(tick -> digest.equals(tick.calendarDigest())).toList();
        if (matching.size() > 1) {
            log.warn("graph round: {} schedulers alive (single writer expected; right after a crash restart the old row ages out)",
                    matching.size());
        }
        return matching.stream().findFirst();
    }
}
