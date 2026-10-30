package com.zoop.feedback;

import static org.junit.jupiter.api.Assertions.*;
import static org.mockito.ArgumentMatchers.*;
import static org.mockito.Mockito.*;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.*;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.*;
import com.zoop.auth.service.MemberSessionService;
import com.zoop.auth.service.SessionCookie;
import com.zoop.chat.dto.ChatJob;
import com.zoop.chat.dto.ChatResult;
import com.zoop.chat.service.ChatService;
import com.zoop.common.exception.*;
import com.zoop.common.request.RequestIdFilter;
import com.zoop.document.evidence.dto.EvidenceResponse;
import com.zoop.document.evidence.service.EvidenceService;
import jakarta.servlet.http.Cookie;
import java.time.Instant;
import java.util.*;
import org.junit.jupiter.api.*;
import org.junit.jupiter.api.condition.EnabledIfEnvironmentVariable;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.test.context.bean.override.mockito.MockitoBean;
import org.springframework.test.web.servlet.MockMvc;
import org.springframework.test.web.servlet.setup.MockMvcBuilders;
import org.springframework.transaction.annotation.Transactional;
import org.springframework.web.context.WebApplicationContext;
import tools.jackson.databind.ObjectMapper;

/** Real HTTP authorization/CSRF + PostgreSQL; saved-result readability is a synthetic guarded boundary, no model call. */
@SpringBootTest(properties={"ZOOP_AUTH_CSRF_ACTIVE_KEY_ID=test","ZOOP_AUTH_CSRF_KEYS=test=AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA","ZOOP_AUTH_ALLOWED_ORIGINS=https://zoop.example"})
@EnabledIfEnvironmentVariable(named="DB_URL",matches="jdbc:postgresql:.*") @Tag("auth-postgres") @Transactional
class AiResultFeedbackPostgresTest {
    @Autowired WebApplicationContext context;@Autowired RequestIdFilter ids;@Autowired JdbcTemplate jdbc;
    @Autowired MemberSessionService sessions;@Autowired ObjectMapper mapper;@Autowired AdminFeedbackService statistics;
    @MockitoBean ChatService chat;@MockitoBean EvidenceService evidence;
    MockMvc mvc;String member,csrf,message,job,version;Cookie cookie;
    @BeforeEach void setup(){
        mvc=MockMvcBuilders.webAppContextSetup(context).addFilters(ids).build();member="feedback-"+UUID.randomUUID();
        jdbc.update("INSERT INTO members(id,analytics_key,email,email_key,display_name,password_hash,signup_method,status,completed,tutorial_completed,settings_version,created_at,updated_at) VALUES(?,?,?,?,?,'test-hash','email','active',true,true,1,now(),now())",member,member,member+"@example.com",member+"@example.com","Synthetic Member");
        var session=sessions.issue(member,null,"synthetic-feedback");cookie=new Cookie(SessionCookie.NAME,session.token());csrf=session.response().csrfToken();
        String conversation="session-"+UUID.randomUUID();job="job-"+UUID.randomUUID();message="message-"+UUID.randomUUID();
        jdbc.update("INSERT INTO chat_sessions(id,member_id,created_at,updated_at) VALUES(?,?,now(),now())",conversation,member);
        jdbc.update("""
          INSERT INTO chat_jobs(id,session_id,seq,question,request_hash,asked_at,frozen_context,frozen_selection,status,outcome,message_id,result,result_schema_version,created_at,updated_at,finished_at)
          VALUES(?,?,1,'합성 질문',repeat('a',64),now(),'{}','{"contextIds":[],"evidenceIds":[],"evidencePool":[]}','completed','answered',?,'{"answer":"합성 답변"}','synthetic-v1',now(),now(),now())
          """,job,conversation,message);
        var result=new ChatResult("answered",message,"합성 답변",List.of(),"general_knowledge",null,List.of(),List.of(),List.of(),null,List.of(),null,List.of(),null,"complete",List.of());
        var guarded=new ChatJob(job,conversation,1,"합성 질문","completed",null,"answered",Instant.now(),null,null,null,result,1,Instant.now(),Instant.now(),Instant.now());version=guarded.feedbackVersion();
        when(chat.getJob(any(),eq(job))).thenReturn(guarded);
    }
    org.springframework.test.web.servlet.ResultActions vote(String feature,String target,String v,String value,String reason)throws Exception{
        var body=mapper.createObjectNode().put("feature",feature).put("targetId",target).put("targetVersion",v).put("value",value).put("reason",reason);
        return mvc.perform(put("/api/v1/feedback").cookie(cookie).header("Origin","https://zoop.example").header("X-CSRF-Token",csrf).contentType("application/json").content(body.toString()));
    }
    @Test void chatVoteRoundTripIdempotencyVersionAndCancellation()throws Exception{
        vote("chatbot_answer",message,version,"down","판단 근거가 부족해요").andExpect(status().isOk());
        var timestamp=jdbc.queryForObject("SELECT updated_at FROM ai_result_feedback WHERE member_id=?",java.sql.Timestamp.class,member);
        vote("chatbot_answer",message,version,"down","판단 근거가 부족해요").andExpect(status().isOk());
        assertEquals(timestamp,jdbc.queryForObject("SELECT updated_at FROM ai_result_feedback WHERE member_id=?",java.sql.Timestamp.class,member));
        mvc.perform(get("/api/v1/feedback").cookie(cookie).param("feature","chatbot_answer").param("targetIds",message)).andExpect(status().isOk()).andExpect(jsonPath("$.items[0].reason").value("판단 근거가 부족해요"));
        assertEquals(1,statistics.summary("all",null,null).at("/features/2/down").asInt());
        vote("chatbot_answer",message,"stale-version","up",null).andExpect(status().isConflict());
        when(chat.getJob(any(),eq(job))).thenThrow(new CustomException(ErrorCode.VERSION_UNAVAILABLE));
        vote("chatbot_answer",message,version,"none",null).andExpect(status().isOk());
        assertEquals(0,statistics.summary("all",null,null).at("/features/2/total").asInt());
    }
    @Test void privateForeignAnswerAndUnavailableSourceAreNotCountedAsZero()throws Exception{
        String stranger="other-"+UUID.randomUUID();jdbc.update("UPDATE chat_sessions SET member_id=? WHERE id=(SELECT session_id FROM chat_jobs WHERE id=?)",member,job);
        vote("chatbot_answer",stranger,version,"up",null).andExpect(status().isNotFound());
        vote("chatbot_answer",message,version,"down","합성 사유").andExpect(status().isOk());
        when(chat.getJob(any(),eq(job))).thenThrow(new CustomException(ErrorCode.SOURCE_UNAVAILABLE));
        assertThrows(CustomException.class,()->statistics.summary("all",null,null));
    }
    @Test void newsSummaryUsesProvidedVerifiedVersionAndRejectsUnavailableSummary()throws Exception{
        String article="article-"+UUID.randomUUID(),text="text-"+UUID.randomUUID(),id="evidence-"+UUID.randomUUID();
        jdbc.update("INSERT INTO artifacts(id,kind,storage_uri,sha256,bytes,media_type,created_at) VALUES(?,'extracted_text','synthetic:test',repeat('a',64),2,'text/plain',now())",text);
        jdbc.update("INSERT INTO articles(id,kind,provider,access_status,created_at) VALUES(?,'news','synthetic','available',now())",article);
        jdbc.update("INSERT INTO article_versions(article_id,version,publication_precision,text_artifact_id,collected_at) VALUES(?,'v1','unknown',?,now())",article,text);
        jdbc.update("INSERT INTO evidence(id,article_id,article_version,text_artifact_id,quote,start_offset,end_offset,offset_unit,input_kind,raw_locator_ids,created_at) VALUES(?,?,'v1',?,'합성',0,2,'unicode_code_point','body','[\"synthetic-locator\"]',now())",id,article,text);
        var summary=mapper.createObjectNode().put("resultVersion","summary:synthetic-v1");
        when(evidence.read(eq(id),isNull(),isNull(),isNull(),isNull(),anyString())).thenReturn(new EvidenceResponse(id,"합성",0,2,article,"v1",null,true,List.of(),null,null,"v1",summary,null,null,"summary:synthetic-v1"));
        vote("news_summary",id,"summary:synthetic-v1","up",null).andExpect(status().isOk());
        assertEquals(1,statistics.summary("all",null,null).at("/features/3/up").asInt());
        vote("news_summary",id,"stale","down","합성").andExpect(status().isConflict());
        when(evidence.read(eq(id),isNull(),isNull(),isNull(),isNull(),anyString())).thenThrow(new CustomException(ErrorCode.EVIDENCE_UNAVAILABLE));
        assertEquals(0,statistics.summary("all",null,null).at("/features/3/total").asInt());
        vote("news_summary",id,"summary:synthetic-v1","none",null).andExpect(status().isOk());
    }
}
