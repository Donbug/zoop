package com.zoop.briefing.impact;

import com.zoop.briefing.impact.BriefingImpacts.*;
import com.zoop.common.json.Canonical;
import tools.jackson.databind.JsonNode;
import tools.jackson.databind.json.JsonMapper;
import java.nio.charset.StandardCharsets;
import java.nio.file.*;
import java.time.*;
import java.util.*;

/** Offline projection of a saved native Jev response. Never sends a provider request. */
final class BriefingSupplementalReviewReader {
    static SupplementalReview read(JsonNode n,JsonNode row,JsonNode assessment,Path root,String company,
            String title,Clock clock,JsonMapper mapper) throws Exception {
        var basis=row.path("basis");
        check(text(n,"mode").equals("supplemental_historical_simulation")
                &&text(n,"roundId").equals(text(basis,"roundId"))&&text(n,"eventId").equals(text(basis,"eventId"))
                &&text(n,"companyId").equals(company)&&text(n,"previousLabel").equals(text(assessment,"label"))
                &&!n.path("historicalVersionVerified").asBoolean(true));
        Instant time=Instant.parse(text(n,"assessedAt")),cutoff=Instant.parse(text(basis,"dataAsOf"));
        check(time.isAfter(cutoff)&&!time.isAfter(clock.instant().plusSeconds(60)));
        var input=file(n.path("input"),root,mapper);var request=file(n.path("request"),root,mapper);
        var receipt=file(n.path("receipt"),root,mapper);
        check(input.path("original").path("basis").equals(basis)
                &&text(input.path("original"),"inputDigest").equals(text(row,"inputDigest")));
        var previous=mapper.readTree(row.toString());
        for(var a:previous.path("assessments"))((tools.jackson.databind.node.ObjectNode)a).remove("supplementalReview");
        check(previous.equals(input.path("original")));
        check(text(receipt,"format").equals("zoop-live-receipt-1")&&text(receipt,"stage").equals("verify-impact")
                &&text(request,"stage").equals("verify-impact")&&text(request,"provider").equals("typesafe-native")
                &&text(receipt.path("model"),"requested").equals("jev-1.14.0")
                &&text(receipt.path("model"),"reported").equals("jev-1.14.0")
                &&receipt.path("http").path("status").asInt()==200
                &&!receipt.path("http").path("truncated").asBoolean(true));
        String body=text(receipt.path("http"),"bodyText");
        check(Canonical.sha256(body).equals(text(receipt.path("http"),"bodySha256")));
        String digest=Canonical.digest(request.path("body"));
        check(digest.equals(text(request,"requestDigest"))&&digest.equals(text(receipt,"requestDigest"))
                &&request.path("expect").equals(receipt.path("expect"))
                &&text(request,"bindingIdentity").equals(text(receipt,"bindingIdentity")));
        var candidate=input.path("candidate");var state=request.path("body").path("state");
        boolean named=false;
        for(var name:candidate.path("target").path("names"))
            if(name.isString()&&name.asString().equals(text(assessment,"companyName")))named=true;
        check(named&&text(request.path("body"),"model").equals("jev-1.14.0")
                &&text(receipt.path("expect"),"kind").equals("verify-impact")
                &&text(state.path("target"),"kind").equals("company")
                &&state.path("target").equals(state.path("relation").path("subject")));
        check(text(candidate,"impactedCompanyId").equals(company)
                &&text(candidate.path("target"),"ref").equals(company)
                &&text(candidate.path("relationFacts").path("subject"),"ref").equals(company)
                &&text(candidate.path("relationFacts").path("object"),"ref").equals(text(basis,"eventId"))
                &&text(candidate.path("relationFacts"),"type").equals("PARTICIPATES_IN")
                &&candidate.path("relationFacts").path("object").path("names").size()==1
                &&candidate.path("relationFacts").path("object").path("names").get(0).asString().equals(title)
                &&state.path("target").path("names").equals(candidate.path("target").path("names")));
        check(state.path("relation").equals(nativeRelation(candidate.path("relationFacts"),mapper)));
        var ids=receipt.path("expect").path("quoteIds");var quotes=candidate.path("quotes");
        check(ids.isArray()&&quotes.isArray()&&quotes.size()>0&&quotes.size()<=16&&ids.size()==quotes.size()
                &&state.path("quotes").size()==quotes.size()
                &&request.path("body").path("questions").size()==quotes.size()+1);
        JsonNode response=mapper.readTree(body);check(text(response,"model").equals("jev-1.14.0"));
        var answers=response.path("answers");check(answers.isObject()&&answers.size()==quotes.size()+1);
        String target=choice(answers.path("target"),Set.of("supported","contradicted","insufficient"),false);
        check(!target.equals("contradicted"));
        boolean positive=false,negative=false,uncertain=false;
        Set<String> seen=new HashSet<>();List<EffectEvidence> evidence=new ArrayList<>();
        for(int i=0;i<quotes.size();i++) {
            var q=quotes.get(i);String id=text(q,"quoteId");
            check(seen.add(id)&&ids.get(i).asString().equals(id)
                    &&text(state.path("quotes").get(i),"label").equals("Q"+(i+1))
                    &&text(state.path("quotes").get(i),"text").equals(text(q,"text")));
            var fact=findFact(q,input.path("facts"));
            check(fact!=null);FactEvidence verified=source(fact,basis,assessment.path("evidencePlan").path("research"),root,cutoff);
            check(verified.quote().equals(text(q,"text")));
            int relativeStart=fact.path("start").asInt();
            for(var original:basis.path("evidence"))if(original.path("documentId").asString().equals(verified.articleId()))
                relativeStart-=original.path("bodyContext").path("start").asInt();
            check(q.path("start").asInt(-1)==relativeStart
                    &&q.path("end").asInt(-1)==relativeStart+verified.quote().codePointCount(0,verified.quote().length()));
            String effect=choice(answers.path("quote-"+i),Set.of("positive","negative","neutral","uncertain"),true);
            evidence.add(new EffectEvidence(id,effect,verified.quote(),verified.articleId(),verified.articleVersion(),
                    verified.title(),verified.url(),verified.publishedAt(),verified.start(),verified.end()));
            positive|=effect.equals("positive");negative|=effect.equals("negative");uncertain|=effect.equals("uncertain");
        }
        String label=uncertain||target.equals("insufficient")?"undetermined":positive&&negative?"mixed":positive?"positive":negative?"negative":"undetermined";
        check(label.equals(text(n,"label"))&&target.equals(text(n,"targetVerdict")));
        List<ReviewFact> facts=new ArrayList<>();check(n.path("confirmedFacts").isArray()&&!n.path("confirmedFacts").isEmpty()
                &&n.path("confirmedFacts").size()<=8);
        for(var f:n.path("confirmedFacts")) {
            List<String> refs=new ArrayList<>();check(f.path("evidenceIds").isArray()&&!f.path("evidenceIds").isEmpty());
            for(var ref:f.path("evidenceIds")) {check(ref.isString()&&seen.contains(ref.asString())&&!refs.contains(ref.asString()));refs.add(ref.asString());}
            facts.add(new ReviewFact(text(f,"text"),List.copyOf(refs)));
        }
        return new SupplementalReview("supplemental_historical_simulation",time,text(n,"previousLabel"),label,target,
                "jev-1.14.0",text(n,"summary"),text(n,"limitations"),List.copyOf(facts),List.copyOf(evidence),Canonical.digest(n),false);
    }
    private static JsonNode findFact(JsonNode quote,JsonNode facts) {
        JsonNode result=null;
        for(var f:facts)if(text(f,"articleId").equals(text(quote,"documentId"))
                &&text(f,"articleVersion").replace("sha256-","").equals(text(quote,"documentVersion"))
                &&text(f,"quote").equals(text(quote,"text"))) {check(result==null);result=f;}
        return result;
    }
    private static FactEvidence source(JsonNode f,JsonNode basis,JsonNode research,Path root,Instant cutoff) throws Exception {
        if(!text(f,"articleId").startsWith("supplement-"))return BriefingImpactReviewService.sourceQuote(f,basis,cutoff);
        JsonNode s=null;for(var v:research.path("sources"))if(text(f,"sourceEvidenceId").equals(text(v,"id")))s=v;
        check(s!=null&&text(f,"articleId").equals("supplement-"+text(s,"id"))
                &&text(f,"articleVersion").equals("sha256-"+text(s,"textSha256"))
                &&text(f,"title").equals(text(s,"title"))&&text(f,"url").equals(text(s,"url"))
                &&text(f,"publishedAt").equals(text(s,"publishedAt")));
        byte[] bytes=read(root,text(s,"textPath"),"supplements/");
        check(Canonical.sha256(bytes).equals(text(s,"textSha256")));
        String body=new String(bytes,StandardCharsets.UTF_8),quote=text(f,"quote");
        check(f.path("start").isIntegralNumber()&&f.path("end").isIntegralNumber());
        int start=f.path("start").asInt(),end=f.path("end").asInt();
        check(start>=0&&end>start&&end<=body.codePointCount(0,body.length())
                &&body.substring(body.offsetByCodePoints(0,start),body.offsetByCodePoints(0,end)).equals(quote));
        Instant published=Instant.parse(text(f,"publishedAt"));check(!published.isAfter(cutoff));
        return new FactEvidence(text(f,"id"),quote,text(f,"articleId"),text(f,"articleVersion"),text(f,"title"),text(f,"url"),published,start,end);
    }
    private static JsonNode nativeRelation(JsonNode source,JsonMapper mapper) {
        var n=(tools.jackson.databind.node.ObjectNode)mapper.readTree(source.toString());
        ((tools.jackson.databind.node.ObjectNode)n.path("subject")).remove("ref");
        ((tools.jackson.databind.node.ObjectNode)n.path("object")).remove("ref");
        return n;
    }
    /** Same provisional p>=.90/conf>=.80 policy as the native pipeline; uncertain never becomes neutral. */
    private static String choice(JsonNode n,Set<String> options,boolean effect) {
        check(text(n,"type").equals("choice"));String chosen=text(n,"choice");check(options.contains(chosen));
        var p=n.path("probabilities");check(p.isObject()&&p.size()==options.size());
        double sum=0,maximum=-1;for(String option:options) {
            check(p.path(option).isNumber());double v=p.path(option).asDouble();
            check(Double.isFinite(v)&&v>=0&&v<=1);sum+=v;maximum=Math.max(maximum,v);
        }
        check(Math.abs(sum-1)<=.02&&n.path("confidence").isNumber());
        double confidence=n.path("confidence").asDouble(),prob=p.path(chosen).asDouble();
        check(Double.isFinite(confidence)&&confidence>=0&&confidence<=1&&prob+1e-9>=maximum);
        return prob>=.90&&confidence>=.80?chosen:effect?"uncertain":"insufficient";
    }
    private static JsonNode file(JsonNode ref,Path root,JsonMapper mapper) throws Exception {
        byte[] raw=read(root,text(ref,"path"),"rechecks/");
        check(raw.length==ref.path("bytes").asLong(-1)&&Canonical.sha256(raw).equals(text(ref,"sha256")));return mapper.readTree(raw);
    }
    private static byte[] read(Path root,String name,String prefix) throws Exception {
        Path relative=Path.of(name);check(name.startsWith(prefix)&&!name.contains("..")&&!relative.isAbsolute()&&relative.normalize().equals(relative));
        Path path=root.resolve(relative);for(Path p=path;p!=null;p=p.getParent())check(!Files.isSymbolicLink(p));
        check(Files.isRegularFile(path,LinkOption.NOFOLLOW_LINKS)&&Files.size(path)<=2_000_000);
        byte[] raw=Files.readAllBytes(path);check(raw.length<=2_000_000);return raw;
    }
    private static String text(JsonNode n,String f){check(n.path(f).isString()&&!n.path(f).asString().isBlank());return n.path(f).asString();}
    private static void check(boolean ok){if(!ok)throw new IllegalArgumentException("invalid_supplemental_review");}
}
