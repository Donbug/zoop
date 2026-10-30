package com.zoop.feedback;

import static org.junit.jupiter.api.Assertions.*;
import com.zoop.chat.dto.*;
import com.zoop.common.response.Metadata;
import java.time.Instant;
import java.util.List;
import org.junit.jupiter.api.Test;

class ChatFeedbackVersionTest {
    ChatJob job(String answer,String request){
        var result=new ChatResult("answered","synthetic-message",answer,List.of(),"general_knowledge",null,List.of(),List.of(),List.of(),null,List.of(),null,List.of(),new Metadata("SYNTHETIC",Instant.now(),null,request,false,List.of()),"complete",List.of());
        return new ChatJob("synthetic-job","synthetic-session",1,"합성 질문","completed",null,"answered",Instant.now(),null,null,null,result,1,Instant.now(),Instant.now(),Instant.now());
    }
    @Test void requestMetadataDoesNotChangeResultIdentityButAnAnswerChangeDoes(){
        assertEquals(job("합성 답변","request-a").feedbackVersion(),job("합성 답변","request-b").feedbackVersion());
        assertNotEquals(job("합성 답변","request-a").feedbackVersion(),job("다른 합성 답변","request-a").feedbackVersion());
    }
}
