package com.zoop.briefing.impact;

import com.zoop.common.json.Canonical;
import com.zoop.common.json.StrictJson;
import tools.jackson.databind.JsonNode;
import tools.jackson.databind.json.JsonMapper;
import tools.jackson.databind.node.ObjectNode;
import java.nio.file.*;
import java.util.*;

/** Replays the actual saved native questions and answers. A manifest is not a verifier verdict. */
final class BriefingNativeImpactPolicy {
    private static final JsonMapper MAPPER=JsonMapper.builder().build();
    static final JsonNode POLICY=resource("/briefing/native-impact-policy-v1.json");
    record Proof(JsonNode receipt,JsonNode request) { }
    private BriefingNativeImpactPolicy() { }

    static JsonNode resource(String path) {
        try(var input=BriefingNativeImpactPolicy.class.getResourceAsStream(path)) {
            check(input!=null);return MAPPER.readTree(input);
        } catch(Exception e){throw new IllegalArgumentException("native_impact_policy_unavailable",e);}
    }
    static JsonNode request(Path root,JsonNode proof,JsonNode receipt) throws Exception {
        String name=proof.path("path").asString();
        JsonNode ref=proof.path("request");
        String relative=ref.isObject()?text(ref,"path"):"requests/"+Path.of(name).getFileName();
        Path p=Path.of(relative);check(relative.startsWith("requests/")&&!relative.contains("..")&&!p.isAbsolute()&&p.normalize().equals(p));
        Path file=root.resolve(p);for(Path parent=file;parent!=null;parent=parent.getParent())check(!Files.isSymbolicLink(parent));
        check(Files.isRegularFile(file,LinkOption.NOFOLLOW_LINKS)&&Files.size(file)<=2_000_000);
        byte[] raw=Files.readAllBytes(file);check(raw.length<=2_000_000);
        if(ref.isObject())check(Canonical.sha256(raw).equals(text(ref,"sha256"))&&raw.length==ref.path("bytes").asLong(-1));
        var request=StrictJson.parseObject(raw).node();
        check(text(request,"stage").equals(text(receipt,"stage"))
                &&text(request,"requestDigest").equals(Canonical.digest(request.path("body")))
                &&text(request,"requestDigest").equals(text(receipt,"requestDigest"))
                &&text(request,"bindingIdentity").matches("[a-f0-9]{64}")
                &&text(request,"bindingIdentity").equals(text(receipt,"bindingIdentity"))
                &&request.path("expect").equals(receipt.path("expect")));
        return request;
    }
    static ObjectNode questions(int count) {
        check(count>0&&count<=16);var out=MAPPER.createObjectNode();var labels=new ArrayList<String>();
        for(int i=1;i<=count;i++)labels.add("Q"+i);
        question(out.putObject("target"),text(POLICY,"targetQuestion").replace("{labels}",String.join(", ",labels)),POLICY.path("targetCriteria"));
        for(int i=0;i<count;i++)question(out.putObject("quote-"+i),text(POLICY,"effectQuestion").replace("{label}","Q"+(i+1)),POLICY.path("effectCriteria"));
        return out;
    }
    private static void question(ObjectNode node,String text,JsonNode criteria) {
        node.put("type","choice");node.putObject("instructions").put("task",text(POLICY,"task")).put("question",text);
        node.set("criteria",criteria.deepCopy());
    }
    static void verifyRequest(JsonNode request) {
        var body=request.path("body");int count=body.path("state").path("quotes").size();
        check(text(request,"stage").equals("verify-impact")&&text(request,"provider").equals("typesafe-native")
                &&text(request,"schemaDigest").equals(text(POLICY,"adapterIdentity"))
                &&text(body,"model").equals("jev-1.14.0")&&body.path("questions").equals(questions(count)));
    }
    static JsonNode relation(String company,JsonNode names,String event,String title,boolean nativeForm) {
        var n=MAPPER.createObjectNode().put("type","PARTICIPATES_IN").put("direction","directed")
                .put("connection","direct").putNull("businessScope").putNull("productScope");
        var subject=n.putObject("subject").put("kind","company");subject.set("names",names.deepCopy());
        var object=n.putObject("object").put("kind","event");object.putArray("names").add(title);
        if(!nativeForm){subject.put("ref",company);object.put("ref",event);}
        n.putObject("validity").putNull("from").putNull("until");n.putArray("countries");n.putArray("path");return n;
    }
    static boolean allowedNames(String company,String name,JsonNode names) {
        Set<String> allowed=new HashSet<>();allowed.add(name);
        for(var c:resource("/company/demo-companies.json").path("companies"))if(company.equals(c.path("company_id").asString())) {
            allowed.add(c.path("name").asString());for(var a:c.path("aliases"))allowed.add(a.asString());
        }
        var seen=new HashSet<String>();boolean named=false;
        if(!names.isArray()||names.isEmpty())return false;
        for(var v:names){if(!v.isString()||!allowed.contains(v.asString())||!seen.add(v.asString()))return false;named|=name.equals(v.asString());}
        return named;
    }
    static void assessment(JsonNode assessment,JsonNode basis,String title,List<Proof> proofs,boolean repaired) {
        String company=text(assessment,"companyId"),name=text(assessment,"companyName");
        List<Proof> generators=proofs.stream().filter(p->"impact".equals(p.receipt().path("stage").asString())
                &&company.equals(generationInput(p.request()).path("relation").path("subject").path("ref").asString())).toList();
        check(generators.size()==1);var generation=generators.getFirst();
        generation(generation.request(),basis,company,name,title);
        var answer=StrictJson.parseObject(text(generation.receipt().path("http"),"bodyText")).node();
        check(text(answer,"model").startsWith("gpt-6-luna")&&answer.path("choices").size()==1
                &&text(answer.path("choices").get(0),"finish_reason").equals("stop"));
        var produced=StrictJson.parseObject(text(answer.path("choices").get(0).path("message"),"content")).node();
        check(text(produced,"schemaVersion").equals("zoop-impact-response-1")&&text(produced,"producerVersion").equals("zoop-impact-producer-1")
                &&produced.path("impacts").isArray()&&produced.path("impacts").size()<=2);
        JsonNode proposal=null;for(var p:produced.path("impacts"))if(company.equals(p.path("impactedCompanyId").asString())){check(proposal==null);proposal=p;}
        String status=text(assessment,"status");
        if(status.equals("not-proposed")){check(proposal==null);return;}
        check(proposal!=null);
        if(!status.equals("verified"))return; // No directional verdict is exposed for rejected results.
        List<Proof> verifiers=proofs.stream().filter(p->"verify-impact".equals(p.receipt().path("stage").asString())
                &&allowedNames(company,name,p.request().path("body").path("state").path("target").path("names"))).toList();
        check(verifiers.size()==1);var verifier=verifiers.getFirst();verifyRequest(verifier.request());
        var state=verifier.request().path("body").path("state");
        check(state.path("target").equals(state.path("relation").path("subject"))
                &&state.path("relation").equals(relation(company,state.path("target").path("names"),text(basis,"eventId"),title,true)));
        var quotes=assessment.path("evidence");var ids=verifier.receipt().path("expect").path("quoteIds");
        check(quotes.isArray()&&!quotes.isEmpty()&&quotes.size()==ids.size()&&quotes.size()==state.path("quotes").size());
        var nativeAnswer=StrictJson.parseObject(text(verifier.receipt().path("http"),"bodyText")).node();
        check(text(nativeAnswer,"model").equals("jev-1.14.0")&&nativeAnswer.path("answers").isObject()
                &&nativeAnswer.path("answers").size()==quotes.size()+1);
        String target=BriefingSupplementalReviewReader.choice(nativeAnswer.path("answers").path("target"),Set.of("supported","contradicted","insufficient"),false);
        check(!target.equals("contradicted")&&target.equals(text(assessment,"targetVerdict")));
        for(int i=0;i<quotes.size();i++) {
            var q=quotes.get(i);check(text(q,"id").equals(ids.get(i).asString())
                    &&text(state.path("quotes").get(i),"label").equals("Q"+(i+1))
                    &&text(q,"quote").equals(text(state.path("quotes").get(i),"text")));
            String effect=BriefingSupplementalReviewReader.choice(nativeAnswer.path("answers").path("quote-"+i),Set.of("positive","negative","neutral","uncertain"),true);
            check(effect.equals(text(q,"effect")));
            // Expanded paragraphs may preserve a producer's anchor only when the repair is explicit.
            boolean bound=false;
            for(String side:List.of("supporting","opposing"))for(var c:proposal.path(side))if(text(q,"articleId").equals(c.path("documentId").asString())
                    &&text(q,"articleVersion").replace("sha256-","").equals(c.path("documentVersion").asString().replace("sha256-",""))
                    &&(text(q,"quote").equals(c.path("quote").asString()) || repaired&&text(q,"quote").contains(c.path("quote").asString())))bound=true;
            check(bound || repaired); // Repaired context is source-checked and independently judged above.
        }
    }
    static JsonNode generationInput(JsonNode request) {
        var messages=request.path("body").path("messages");check(messages.isArray()&&messages.size()==2);
        var envelope=StrictJson.parseObject(text(messages.get(1),"content")).node();check(text(envelope,"stage").equals("impact"));
        return envelope.path("input");
    }
    private static void generation(JsonNode request,JsonNode basis,String company,String name,String title) {
        var body=request.path("body");var messages=body.path("messages");var input=generationInput(request);
        check(text(request,"provider").equals("openai-compatible")&&text(body,"model").equals("gpt-6-luna")
                &&text(request,"schemaDigest").equals(text(POLICY,"generationSchemaDigest"))
                &&text(request,"promptVersion").equals(text(POLICY,"generationPromptVersion"))
                &&text(messages.get(0),"role").equals("system")&&text(messages.get(0),"content").equals(text(POLICY,"generationSystem"))
                &&text(messages.get(1),"role").equals("user")
                &&body.path("response_format").path("json_schema").path("schema").equals(POLICY.path("generationSchema")));
        var names=MAPPER.createArrayNode().add(name);var relation=relation(company,names,text(basis,"eventId"),title,false);
        check(input.path("relation").equals(relation)&&input.path("companies").isArray()&&input.path("companies").size()==1
                &&input.path("companies").get(0).equals(relation.path("subject")));
        var docs=MAPPER.createArrayNode();var refs=MAPPER.createArrayNode();
        for(var e:basis.path("evidence")) {
            docs.addObject().put("documentId",text(e,"documentId")).put("documentVersion",text(e,"documentVersion"))
                    .put("title",text(e,"title")).put("text",text(e.path("bodyContext"),"text"));
            refs.addObject().put("quoteId",text(e,"id")).put("text",text(e,"quote"));
        }
        check(input.path("documents").equals(docs)&&input.path("relationQuotes").equals(refs));
    }
    private static String text(JsonNode n,String f){check(n.path(f).isString()&&!n.path(f).asString().isBlank());return n.path(f).asString();}
    private static void check(boolean ok){if(!ok)throw new IllegalArgumentException("native_impact_proof_mismatch");}
}
