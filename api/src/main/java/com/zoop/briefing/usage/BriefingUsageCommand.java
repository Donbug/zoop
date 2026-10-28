package com.zoop.briefing.usage;

import java.io.BufferedReader;
import java.io.InputStreamReader;
import java.nio.charset.StandardCharsets;
import java.nio.file.Path;
import java.time.Duration;
import java.util.Arrays;

import com.zoop.common.json.StrictJson;
import org.springframework.jdbc.core.namedparam.NamedParameterJdbcTemplate;
import org.springframework.jdbc.datasource.DataSourceTransactionManager;
import org.springframework.jdbc.datasource.DriverManagerDataSource;
import tools.jackson.databind.node.ObjectNode;

/** Private operator pipe, never an HTTP endpoint. Credentials are read only from the normal DB_* environment. */
public final class BriefingUsageCommand {
    private BriefingUsageCommand() { }
    public static void main(String[] args) throws Exception {
        if(!Arrays.equals(args,new String[]{"--stdio"})) throw new IllegalArgumentException("Use --stdio");
        String url=required("DB_URL"), user=required("DB_USERNAME"), root=required("BRIEFING_USAGE_ARTIFACT_ROOT");
        if(!url.startsWith("jdbc:postgresql:")) throw new IllegalArgumentException("PostgreSQL required");
        DriverManagerDataSource source=new DriverManagerDataSource(url,user,System.getenv().getOrDefault("DB_PASSWORD",""));
        var ledger=new BriefingUsageLedger(new NamedParameterJdbcTemplate(source),new DataSourceTransactionManager(source),
            Path.of(root),Duration.ofSeconds(Long.parseLong(System.getenv().getOrDefault("BRIEFING_USAGE_LEASE_SECONDS","120"))));
        try(BufferedReader input=new BufferedReader(new InputStreamReader(System.in,StandardCharsets.UTF_8))) {
            for(String line; (line=readBounded(input))!=null;) {
                ObjectNode response;
                try {response=ledger.execute(StrictJson.parseObject(line));response.put("ok",true);}
                catch(BriefingUsageLedger.Rejected error) {response=StrictJson.newObject().put("ok",false).put("code",error.getMessage());}
                catch(RuntimeException error) {response=StrictJson.newObject().put("ok",false).put("code","ledger_command_rejected");}
                System.out.println(new String(StrictJson.write(response),StandardCharsets.UTF_8));System.out.flush();
            }
        }
    }
    private static String required(String key) {String value=System.getenv(key);if(value==null||value.isBlank())throw new IllegalArgumentException("Missing "+key);return value;}
    private static String readBounded(BufferedReader input) throws java.io.IOException {
        StringBuilder line=new StringBuilder();for(int c;(c=input.read())!=-1;){if(c=='\n')return line.toString();
            if(line.length()>=65536)throw new IllegalArgumentException("Ledger command exceeds limit");line.append((char)c);}
        return line.isEmpty()?null:line.toString();
    }
}
