package com.zoop.briefing.server;
import static org.junit.jupiter.api.Assertions.*;
import com.zoop.common.json.StrictJson;
import java.sql.Timestamp;
import java.time.Instant;
import java.util.HashMap;
import org.junit.jupiter.api.Test;
class BriefingSourceClockTest {
    @Test void dateNeverBecomesMidnightAndForgedObservationIsRejected() {
        var row=new HashMap<String,Object>();row.put("publication_precision","day");row.put("published_date",java.sql.Date.valueOf("2026-11-03"));
        row.put("collected_at",Timestamp.from(Instant.parse("2026-11-03T10:34:25Z")));
        var clock=BriefingSourceClock.read(row);assertNull(clock.publishedAt());
        var pin=StrictJson.newObject();clock.put(pin);assertTrue(clock.matches(StrictJson.Obj.of(pin)));
        pin.put("availableAt","2026-11-03T00:00:00Z");assertFalse(clock.matches(StrictJson.Obj.of(pin)));
        pin.put("publishedAt","2026-11-03T00:00:00Z");assertFalse(clock.matches(StrictJson.Obj.of(pin)));
    }
    @Test void unknownAndFutureDaysAreNotEligible() {
        var row=new HashMap<String,Object>();row.put("publication_precision","unknown");assertThrows(IllegalArgumentException.class,()->BriefingSourceClock.read(row));
        row.put("publication_precision","day");row.put("published_date",java.sql.Date.valueOf("2026-11-04"));
        row.put("collected_at",Timestamp.from(Instant.parse("2026-11-03T10:00:00Z")));
        assertThrows(IllegalArgumentException.class,()->BriefingSourceClock.read(row));
    }
}
