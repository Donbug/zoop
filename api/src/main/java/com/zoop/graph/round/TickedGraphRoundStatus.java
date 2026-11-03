package com.zoop.graph.round;

import java.time.Clock;
import java.time.Instant;
import java.util.List;
import java.util.Optional;
import com.zoop.graph.round.GraphRoundTicks.Tick;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

/**
 * The scheduler status of a web process that runs no scheduler itself (the public web with the admin round commands, #55 PR-P4):
 * read from the writers' heartbeats. Enabled while one is alive (beat younger than three of its intervals); the last pass and the
 * next slot are the freshest live writer's. When the heartbeats cannot be read it says disabled, so the commands answer 404 as they
 * do without a scheduler.
 */
public final class TickedGraphRoundStatus implements GraphRoundStatus {
    private static final Logger log = LoggerFactory.getLogger(TickedGraphRoundStatus.class);

    private final GraphRoundTicks ticks;
    private final Clock clock;

    public TickedGraphRoundStatus(GraphRoundTicks ticks, Clock clock) {
        this.ticks = ticks;
        this.clock = clock;
    }

    @Override
    public boolean enabled() {
        return live().isPresent();
    }

    @Override
    public Optional<Instant> nextSlotAt() {
        return live().flatMap(Tick::nextSlotAt);
    }

    @Override
    public Optional<Instant> lastTickAt() {
        return live().flatMap(Tick::lastPassAt);
    }

    /** The freshest live writer. More than one alive breaks the single-writer rule; that is logged, the status shows the freshest. */
    private Optional<Tick> live() {
        List<Tick> all;
        try {
            all = ticks.all();
        } catch (RuntimeException unavailable) {
            log.warn("graph round heartbeats unreadable ({})", unavailable.getClass().getSimpleName());
            return Optional.empty();
        }
        Instant now = clock.instant();
        List<Tick> alive = all.stream().filter(tick -> tick.alive(now)).toList();
        if (alive.size() > 1) log.warn("graph round: {} schedulers alive (single writer expected)", alive.size());
        return alive.stream().findFirst();
    }
}
