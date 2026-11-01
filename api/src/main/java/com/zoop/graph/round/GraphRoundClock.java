package com.zoop.graph.round;

import java.time.Duration;
import java.time.Instant;
import java.time.LocalDate;
import java.time.LocalTime;
import java.time.ZoneId;
import java.time.ZonedDateTime;
import java.time.format.DateTimeFormatter;
import java.time.temporal.ChronoUnit;
import java.util.ArrayList;
import java.util.List;
import java.util.Optional;

/**
 * The slot calendar of the periodic round: every calendar day (no weekday or holiday rule, the AI tick answers
 * {@code no_new_material} outside its window), {@code slotCount} regular slots from {@code firstSlot} every {@code slotInterval}
 * in {@code zone}, plus the freeze-only slots (the one after the operating hours, team decision 8). The round id of a slot is
 * {@code round-yyyyMMdd'T'HHmm} in that zone, the form the row's CHECK and the AI contract expect. Pure: no clock of its own.
 */
public final class GraphRoundClock {
    private static final DateTimeFormatter ID = DateTimeFormatter.ofPattern("yyyyMMdd'T'HHmm");

    /** One slot of the calendar; {@code freezeOnly} slots ask for a carry-only freeze without a run. */
    public record Slot(String roundId, Instant slotAt, boolean freezeOnly) {
    }

    private final ZoneId zone;
    private final LocalTime first;
    private final Duration interval;
    private final int count;
    private final List<LocalTime> freezeOnly;

    public GraphRoundClock(GraphRoundProperties properties) {
        this(properties.slotZone(), properties.firstSlot(), properties.slotInterval(), properties.slotCount(),
                properties.freezeOnlySlots());
    }

    public GraphRoundClock(ZoneId zone, LocalTime first, Duration interval, int count, List<LocalTime> freezeOnly) {
        this.zone = zone;
        this.first = first;
        this.interval = interval;
        this.count = count;
        this.freezeOnly = List.copyOf(freezeOnly);
    }

    /** The slots with {@code from < slotAt <= to}, oldest first. */
    public List<Slot> slotsBetween(Instant from, Instant to) {
        List<Slot> found = new ArrayList<>();
        if (!to.isAfter(from)) return found;
        LocalDate day = from.atZone(zone).toLocalDate().minusDays(1);
        LocalDate last = to.atZone(zone).toLocalDate().plusDays(1);
        for (; !day.isAfter(last); day = day.plusDays(1)) {
            for (Slot slot : slotsOn(day)) {
                if (slot.slotAt().isAfter(from) && !slot.slotAt().isAfter(to)) found.add(slot);
            }
        }
        found.sort((a, b) -> a.slotAt().compareTo(b.slotAt()));
        return found;
    }

    /** The first slot strictly after {@code now}. */
    public Optional<Instant> nextSlotAt(Instant now) {
        LocalDate day = now.atZone(zone).toLocalDate();
        for (int offset = 0; offset <= 2; offset++) {
            Optional<Instant> next = slotsOn(day.plusDays(offset)).stream().map(Slot::slotAt).filter(at -> at.isAfter(now)).findFirst();
            if (next.isPresent()) return next;
        }
        return Optional.empty();
    }

    /** True when the slot instant is one of the freeze-only times of its day. */
    public boolean freezeOnly(Instant slotAt) {
        LocalTime time = slotAt.atZone(zone).toLocalTime();
        return freezeOnly.contains(time);
    }

    /** {@code round-yyyyMMdd'T'HHmm} of the slot in the calendar's zone. */
    public String roundId(Instant slotAt) {
        return "round-" + ID.format(slotAt.atZone(zone));
    }

    /** The instant cut to its minute, the finest slot a manual start may name. */
    public Instant minute(Instant at) {
        return at.truncatedTo(ChronoUnit.MINUTES);
    }

    /** The regular slots of one day followed by its freeze-only slots, in time order. */
    List<Slot> slotsOn(LocalDate day) {
        List<Slot> slots = new ArrayList<>();
        for (int k = 0; k < count; k++) {
            ZonedDateTime at = day.atTime(first).atZone(zone).plus(interval.multipliedBy(k));
            if (!at.toLocalDate().equals(day)) break; // the calendar never crosses midnight
            slots.add(new Slot(roundId(at.toInstant()), at.toInstant(), false));
        }
        for (LocalTime time : freezeOnly) {
            Instant at = day.atTime(time).atZone(zone).toInstant();
            slots.add(new Slot(roundId(at), at, true));
        }
        slots.sort((a, b) -> a.slotAt().compareTo(b.slotAt()));
        return slots;
    }
}
