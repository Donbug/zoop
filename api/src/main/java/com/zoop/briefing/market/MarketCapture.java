package com.zoop.briefing.market;

import com.zoop.briefing.input.FileBriefingInputStore;
import java.nio.file.Path;
import java.time.*;
import java.util.*;

/** Explicit development prefetch. No credentials/model calls/DB/round creation/publication. */
public final class MarketCapture {
    public static void main(String[] args) throws Exception {
        if(args.length<7||args.length>8||!args[6].equals("--development-read")) throw new IllegalArgumentException(
            "calendar.json date edition roundId previous-cutoff-or-first private-dir --development-read [reuse-snapshot-sha256]");
        var calendar=TradingCalendar.read(Path.of(args[0]));
        var date=LocalDate.parse(args[1]);
        boolean first=args[4].equals("first");
        var context=new BriefingRoundClock.Context(args[3],date,args[2],BriefingRoundClock.scheduledAt(date,args[2]),
            first?null:Instant.parse(args[4]),first,calendar);
        Path output=Path.of(args[5]); var store=new FileBriefingInputStore(output);
        MarketSnapshot snapshot; int calls;
        if(args.length==8) {
            if(!args[7].matches("[a-f0-9]{64}")) throw new IllegalArgumentException("sha256");
            Path path=output.resolve(args[7]+".json");
            snapshot=MarketSnapshot.restore(new FileBriefingInputStore.Staged(path,args[7],java.nio.file.Files.size(path)));
            if(!snapshot.json().path("runContext").equals(context.json())) throw new IllegalArgumentException("Replay context changed");
            calls=0;
        } else {
            Clock clock=Clock.systemUTC();
            if(clock.instant().isAfter(context.scheduledAt())) throw new IllegalArgumentException("Prefetch must finish before cutoff; use an existing saved snapshot after cutoff");
            var receipts=PublicMarketProvider.collect(PublicMarketProvider.live(clock));
            snapshot=MarketSnapshot.freeze(context,receipts,clock.instant(),store); calls=receipts.size();
        }
        var out=TradingCalendar.JSON.createObjectNode().put("newHttpCalls",calls).put("snapshotSha256",snapshot.staged().sha256())
            .put("snapshotBytes",snapshot.staged().bytes()).put("productionAuthorized",false);
        out.set("runContext",snapshot.json().path("runContext"));
        out.set("marketVariables",snapshot.json().path("marketVariables"));
        System.out.println(TradingCalendar.JSON.writeValueAsString(out));
    }
}
