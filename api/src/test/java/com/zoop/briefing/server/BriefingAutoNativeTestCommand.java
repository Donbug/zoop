package com.zoop.briefing.server;

import com.zoop.common.json.StrictJson;
import java.nio.file.Files;
import java.nio.file.Path;
import java.time.Clock;
import java.time.Instant;
import java.time.ZoneOffset;

/** Test-only CLI with a pre-cutoff clock. Production entrypoint never references this class. */
public final class BriefingAutoNativeTestCommand {
    public static void main(String[] args) throws Exception {
        var command=new BriefingNativeCommand(System.getenv(),Clock.fixed(Instant.parse("2026-11-04T00:05:00Z"),ZoneOffset.UTC));
        var request=StrictJson.parseObject(Files.readAllBytes(Path.of(args[1])));
        var result=switch(args[0]){
            case "state" -> command.state();
            case "import" -> command.importNative(request);
            case "activate" -> command.activate(request);
            default -> throw new IllegalArgumentException();
        };
        System.out.println("BRIEFING_SERVER_RESULT="+new String(StrictJson.write(result),java.nio.charset.StandardCharsets.UTF_8));
    }
}
