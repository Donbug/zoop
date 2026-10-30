package com.zoop.admin.briefings;

import com.zoop.artifact.storage.ArtifactFileStore;
import com.zoop.common.json.StrictJson;
import java.nio.file.*;
import java.util.*;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.jdbc.datasource.DataSourceTransactionManager;
import org.springframework.jdbc.datasource.DriverManagerDataSource;
import org.springframework.transaction.support.TransactionTemplate;

/** Non-web operator admission. No model is called and no generation outcome/usage is invented. */
public final class BriefingReprocessInputCommand {
    public static void main(String[] args)throws Exception{
        if(args.length!=6)throw new IllegalArgumentException("Use round-id input-file generation|save_only_generation max-calls authorization-ref enabled");
        String round=args[0],operation=args[2],authorization=args[4];int max=Integer.parseInt(args[3]);
        if(!Set.of("generation","save_only_generation").contains(operation)||max<0||max>16||operation.equals("save_only_generation")&&max!=0||authorization.isBlank()||!Set.of("true","false").contains(args[5]))throw new IllegalArgumentException("Invalid admission");
        Path input=Path.of(args[1]);
        if(Files.isSymbolicLink(input)||!Files.isRegularFile(input,LinkOption.NOFOLLOW_LINKS)||Files.size(input)>4*1024*1024)throw new IllegalArgumentException("Input unavailable");
        byte[] bytes=Files.readAllBytes(input);var json=StrictJson.parseObject(bytes);
        DriverManagerDataSource source=new DriverManagerDataSource(required("DB_URL"),required("DB_USERNAME"),required("DB_PASSWORD"));
        var jdbc=new JdbcTemplate(source);var tx=new TransactionTemplate(new DataSourceTransactionManager(source));
        var rows=jdbc.queryForList("SELECT id FROM briefing_rounds WHERE id=? AND published_at IS NULL",round);
        if(rows.isEmpty())throw new IllegalArgumentException("Only an existing unpublished round may be admitted");
        if(operation.equals("save_only_generation")){
            if(!json.string("schemaVersion").equals("briefing-recorded-result-v1")||!round.equals(json.string("roundId"))||!json.string("purpose").equals("generation")||!json.string("outcome").equals("available")
               ||!"PASS".equals(json.node().path("result").path("verification").path("status").asText()))throw new IllegalArgumentException("A verified recorded generation result is required");
        }
        try(var session=ArtifactFileStore.at(Path.of(required("BRIEFING_USAGE_ARTIFACT_ROOT"))).open()){
            String sha=ArtifactFileStore.sha256(bytes),id="brf-reprocess-input-"+sha;
            var file=session.put("briefing_reprocess_inputs",sha+".json",bytes);
            tx.executeWithoutResult(status->{
                jdbc.update("INSERT INTO artifacts(id,kind,storage_uri,sha256,bytes,media_type,created_at) VALUES(?,'briefing_input',?,?,?,'application/json',clock_timestamp()) ON CONFLICT(id) DO NOTHING",id,file.uri(),sha,file.bytes());
                jdbc.update("""
                    INSERT INTO briefing_reprocess_inputs(round_id,input_artifact_id,operation,max_calls,authorization_ref,enabled) VALUES(?,?,?,?,?,?)
                    ON CONFLICT(round_id) DO UPDATE SET input_artifact_id=excluded.input_artifact_id,operation=excluded.operation,max_calls=excluded.max_calls,authorization_ref=excluded.authorization_ref,enabled=excluded.enabled
                    """,round,id,operation,max,authorization,Boolean.parseBoolean(args[5]));
            });
            System.out.println("{\"admitted\":true,\"newModelCalls\":0}");
        }
    }
    private static String required(String key){String value=System.getenv(key);if(value==null||value.isBlank())throw new IllegalArgumentException("Missing "+key);return value;}
}
