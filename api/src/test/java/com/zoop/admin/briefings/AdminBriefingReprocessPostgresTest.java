package com.zoop.admin.briefings;

import static org.assertj.core.api.Assertions.assertThat;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.*;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.*;
import com.zoop.admin.auth.provision.AdminProvisioningService;
import com.zoop.admin.auth.service.AdminSessionCookie;
import com.zoop.artifact.storage.ArtifactFileStore;
import com.zoop.common.request.RequestIdFilter;
import jakarta.servlet.http.Cookie;
import java.nio.file.*;
import java.util.UUID;
import org.junit.jupiter.api.*;
import org.junit.jupiter.api.condition.EnabledIfEnvironmentVariable;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.test.context.DynamicPropertyRegistry;
import org.springframework.test.context.DynamicPropertySource;
import org.springframework.test.web.servlet.MockMvc;
import org.springframework.test.web.servlet.setup.MockMvcBuilders;
import org.springframework.transaction.annotation.Transactional;
import org.springframework.web.context.WebApplicationContext;
import tools.jackson.databind.ObjectMapper;

@SpringBootTest(properties={"ZOOP_AUTH_CSRF_ACTIVE_KEY_ID=test","ZOOP_AUTH_CSRF_KEYS=test=AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA","ZOOP_AUTH_ALLOWED_ORIGINS=https://zoop.example",
    "zoop.briefing.reprocess.enabled=true","zoop.briefing.reprocess.command=[\"/usr/bin/false\"]","zoop.briefing.reprocess.initial-delay-ms=3600000"})
@EnabledIfEnvironmentVariable(named="DB_URL",matches="jdbc:postgresql:.*")
@Tag("auth-postgres") @Transactional
class AdminBriefingReprocessPostgresTest {
    static Path root;
    static {try{root=Files.createTempDirectory("zoop-reprocess-test-").toRealPath();}catch(Exception e){throw new ExceptionInInitializerError(e);}}
    @DynamicPropertySource static void config(DynamicPropertyRegistry r){r.add("zoop.briefing.reprocess.root",()->root.toString());}
    @Autowired WebApplicationContext context;@Autowired RequestIdFilter ids;@Autowired JdbcTemplate jdbc;
    @Autowired AdminProvisioningService provision;@Autowired ObjectMapper mapper;@Autowired BriefingReprocessWorker worker;
    MockMvc mvc;Cookie cookie;String csrf,round;
    @BeforeEach void setup()throws Exception{
        mvc=MockMvcBuilders.webAppContextSetup(context).addFilters(ids).build();
        String email="reprocess-"+UUID.randomUUID()+"@example.com";provision.provision(email,"Synthetic admin","Synthetic-admin-2026!","test-provision");
        var result=mvc.perform(post("/api/v1/admin/auth/login").header("Origin","https://zoop.example").with(r->{r.setRemoteAddr("192.0.2.215");return r;}).contentType("application/json").content("{\"email\":\""+email+"\",\"password\":\"Synthetic-admin-2026!\"}"))
            .andExpect(status().isOk()).andReturn().getResponse();
        cookie=new Cookie(AdminSessionCookie.NAME,result.getHeader("Set-Cookie").split(";",2)[0].split("=",2)[1]);csrf=mapper.readTree(result.getContentAsString()).path("csrfToken").asText();
        round="reprocess-"+UUID.randomUUID();
        jdbc.update("INSERT INTO briefing_rounds(id,round_date,edition,scheduled_at,window_to,open_start,status) VALUES(?,'1980-01-01','morning','1980-01-01T00:20Z','1980-01-01T00:20Z',true,'failed')",round);
        byte[] input=("{\"schemaVersion\":\"briefing-recorded-result-v1\",\"roundId\":\""+round+"\",\"purpose\":\"generation\",\"outcome\":\"available\",\"result\":{\"verification\":{\"status\":\"PASS\"}}}").getBytes(java.nio.charset.StandardCharsets.UTF_8);
        try(var files=ArtifactFileStore.at(root).open()){
            String artifact="input-"+UUID.randomUUID();var file=files.put("reprocess_test",artifact+".json",input);
            jdbc.update("INSERT INTO artifacts(id,kind,storage_uri,sha256,bytes,media_type,created_at) VALUES(?,'briefing_input',?,?,?,'application/json',clock_timestamp())",artifact,file.uri(),file.sha256(),file.bytes());
            jdbc.update("INSERT INTO briefing_reprocess_inputs(round_id,input_artifact_id,operation,max_calls,authorization_ref) VALUES(?,?,'save_only_generation',0,'synthetic-no-model')",round,artifact);
        }
    }
    org.springframework.test.web.servlet.request.MockHttpServletRequestBuilder request(String key,String reason){return post("/api/v1/admin/briefings/"+round+"/reprocess").cookie(cookie).header("Origin","https://zoop.example").header("X-CSRF-Token",csrf).header("Idempotency-Key",key).contentType("application/json").content("{\"reason\":\""+reason+"\"}");}
    @Test void admissionIsAtomicIdempotentAndCreatesOneFreshAttempt()throws Exception{
        mvc.perform(get("/api/v1/admin/briefings/"+round).cookie(cookie)).andExpect(jsonPath("$.reprocessable").value(true));
        String first=mvc.perform(request("same","합성 저장 복구 확인")).andExpect(status().isAccepted()).andExpect(jsonPath("$.attempts").value(1)).andReturn().getResponse().getContentAsString();
        assertThat(mapper.readTree(mvc.perform(request("same","합성 저장 복구 확인")).andExpect(status().isAccepted()).andReturn().getResponse().getContentAsString())).isEqualTo(mapper.readTree(first));
        mvc.perform(request("same","다른 내용")).andExpect(status().isConflict());mvc.perform(request("other","동시 중복 방지")).andExpect(status().isConflict());
        assertThat(jdbc.queryForObject("SELECT count(*) FROM briefing_attempts WHERE round_id=?",Integer.class,round)).isEqualTo(1);
        assertThat(jdbc.queryForObject("SELECT count(*) FROM briefing_reprocess_jobs WHERE round_id=?",Integer.class,round)).isEqualTo(1);
        assertThat(jdbc.queryForObject("SELECT count(*) FROM audit_logs WHERE target_id=? AND action='briefing.reprocess'",Integer.class,round)).isEqualTo(1);
    }
    @Test void authorizationCsrfAndFutureRoundAreRejectedWithoutAttempts()throws Exception{
        mvc.perform(post("/api/v1/admin/briefings/"+round+"/reprocess").contentType("application/json").content("{\"reason\":\"합성\"}")).andExpect(status().isUnauthorized());
        mvc.perform(request("csrf","합성").header("X-CSRF-Token","wrong")).andExpect(status().isForbidden());
        round="future-"+UUID.randomUUID();
        jdbc.update("INSERT INTO briefing_rounds(id,round_date,edition,scheduled_at,window_to,open_start,status) VALUES(?,'2180-01-01','morning','2180-01-01T00:20Z','2180-01-01T00:20Z',true,'scheduled')",round);
        mvc.perform(request("future","합성")).andExpect(status().isConflict());
        assertThat(jdbc.queryForObject("SELECT count(*) FROM briefing_attempts WHERE round_id=?",Integer.class,round)).isZero();
    }
    @Test void noAdmittedInputOrNoLiveApprovalDoesNotQueueAJob()throws Exception{
        jdbc.update("UPDATE briefing_reprocess_inputs SET operation='generation',max_calls=4 WHERE round_id=?",round);
        mvc.perform(request("live","합성")).andExpect(status().isConflict());
        jdbc.update("UPDATE briefing_reprocess_inputs SET enabled=false WHERE round_id=?",round);
        mvc.perform(request("missing","합성")).andExpect(status().isConflict());
        assertThat(jdbc.queryForObject("SELECT count(*) FROM briefing_reprocess_jobs WHERE round_id=?",Integer.class,round)).isZero();
    }
    @Test void workerFailureIsPreservedAndNextRequestCreatesANewAttempt()throws Exception{
        mvc.perform(request("first","합성 실패")).andExpect(status().isAccepted());worker.tick();
        mvc.perform(get("/api/v1/admin/briefings/"+round).cookie(cookie)).andExpect(jsonPath("$.status").value("failed")).andExpect(jsonPath("$.attemptsLog[0].failureStage").value("admin_worker"));
        mvc.perform(request("next","합성 재시도")).andExpect(status().isAccepted()).andExpect(jsonPath("$.attempts").value(2));
        assertThat(jdbc.queryForObject("SELECT count(*) FROM ai_executions WHERE briefing_attempt_id IN (SELECT id FROM briefing_attempts WHERE round_id=?)",Integer.class,round)).isZero();
    }
    @Test @Transactional(propagation=org.springframework.transaction.annotation.Propagation.NOT_SUPPORTED)
    void actualPythonBridgeAndJavaLedgerCompleteSaveOnlyWithoutPublishingOrCallingAModel()throws Exception{
        Path scripts=Path.of("../scripts/briefing_admin_reprocess.py").toAbsolutePath().normalize();
        var command=java.util.List.of(Path.of(System.getProperty("java.home"),"bin/java").toString(),"-cp",System.getProperty("zoop.briefing.usage.classpath"),"com.zoop.briefing.usage.BriefingUsageCommand","--stdio");
        String encoded=java.util.Base64.getEncoder().encodeToString(mapper.writeValueAsBytes(command));
        Path wrapper=root.resolve("bridge-test.py");
        Files.writeString(wrapper,"import base64,os,runpy,sys\nos.environ['ZOOP_BRIEFING_LEDGER_COMMAND']=base64.b64decode('"+encoded+"').decode()\nsys.argv=sys.argv[1:]\nsys.path.insert(0,os.path.dirname(sys.argv[0]))\nrunpy.run_path(sys.argv[0],run_name='__main__')\n");
        var policy=new BriefingReprocessPolicy(jdbc,mapper,true,false,root.toString(),mapper.writeValueAsString(java.util.List.of("python3",wrapper.toString(),scripts.toString())));
        var actual=new BriefingReprocessWorker(jdbc,policy,mapper,context.getBean(org.springframework.transaction.PlatformTransactionManager.class));
        mvc.perform(request("real-bridge","합성 저장 복구 전체 흐름")).andExpect(status().isAccepted());actual.tick();
        mvc.perform(get("/api/v1/admin/briefings/"+round).cookie(cookie)).andExpect(status().isOk()).andExpect(jsonPath("$.reprocessState").value("completed"))
            .andExpect(jsonPath("$.publishedAt").isEmpty()).andExpect(jsonPath("$.attemptsLog[0].outcome").value("available"));
        assertThat(jdbc.queryForObject("SELECT count(*) FROM ai_executions e JOIN briefing_attempts a ON a.id=e.briefing_attempt_id WHERE a.round_id=? AND e.execution_mode='live'",Integer.class,round)).isZero();
        assertThat(jdbc.queryForObject("SELECT count(*) FROM ai_executions e JOIN briefing_attempts a ON a.id=e.briefing_attempt_id WHERE a.round_id=? AND e.execution_mode='save_only'",Integer.class,round)).isEqualTo(1);
    }
}
