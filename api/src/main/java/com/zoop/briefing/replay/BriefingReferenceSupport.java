package com.zoop.briefing.replay;

import com.zoop.common.json.Canonical;
import com.zoop.common.json.StrictJson;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.HashMap;
import java.util.HashSet;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.Set;

/** Reuse the actual completed semantic verdict, not quote length or an archive's unsupported boolean. */
final class BriefingReferenceSupport {
    record Proof(StrictJson.Obj mention, String requestDigest) { }
    private BriefingReferenceSupport() { }

    static Map<String, Proof> load(BriefingGroupedSimulationRules.Archive archive, Path output) {
        Map<String, StrictJson.Obj> original=new HashMap<>(), documents=new HashMap<>();
        archive.root().objects("issues").forEach(i->i.objects("mentions").forEach(m->original.put(m.string("mentionId"),m)));
        archive.root().objects("documents").forEach(d->documents.put(d.string("documentId"),d));
        Map<String, Proof> result=new LinkedHashMap<>();
        for(var receipt:archive.root().objects("receipts")) {
            if(!"issue_grounding".equals(receipt.string("stage")) || !receipt.bool("usageKnown")
                    || !"completed".equals(receipt.string("status")))continue;
            var recording=BriefingGroupedSimulationRules.recording(receipt,output,true);
            try {
                var request=StrictJson.parseObject(Files.readAllBytes(output.resolve("calls").resolve(receipt.string("requestDigest")+".request.json")));
                require(Canonical.sha256(request.string("instructions")).equals(archive.root().object("identity").object("promptSha256").string("issue_grounding")),"prompt");
            } catch(java.io.IOException e) {throw new IllegalArgumentException("Reference grounding input unavailable",e);}
            var input=recording.input(); var verdicts=recording.answer().object("verdicts");
            require(input.object("authorization").string("sourceSha256").equals(archive.root().string("sourceFileSha256")),"source_authorization");
            Set<String> population=new HashSet<>();input.object("mentions").node().propertyNames().forEach(population::add);verdicts.exactly(population);
            Map<String,StrictJson.Obj> articles=new HashMap<>();input.objects("articles").forEach(a->articles.put(a.string("article_id"),a));
            for(String id:population) {
                var m=original.get(id);var verdict=verdicts.object(id);
                if(m==null || !"SUPPORTED".equals(verdict.string("verdict")))continue;
                var raw=input.object("mentions").object(id);var article=articles.get(m.string("articleId"));var doc=documents.get(m.string("articleId"));
                require(article!=null && doc!=null && doc.string("body").equals(article.string("body"))
                        && Canonical.sha256(article.string("body")).equals(m.string("bodySha256"))
                        && doc.string("url").startsWith("https://") && doc.string("url").equals(article.string("url")),"original_body_and_source");
                require(m.object("grounding").node().equals(verdict.node()) && !raw.bool("background")
                        && m.string("articleId").equals(raw.string("article_id"))
                        && m.string("pocArticleVersion").equals(raw.string("article_version"))
                        && m.string("title").equals(raw.string("title")) && m.string("action").equals(raw.string("action"))
                        && m.string("assertionStatus").equals(raw.string("assertion_status")),"supported_event_binding");
                for(var e:m.objects("evidence")) require(raw.objects("evidence").stream().anyMatch(old->
                        e.string("quote").equals(old.string("quote")) && e.count("start")==old.count("start") && e.count("end")==old.count("end")),"supported_quote_binding");
                // Canonical identity projection can rename a company, but cannot create a participant/role.
                if(m.has("companyProjection")) for(var audit:m.object("companyProjection").objects("audit"))
                    require(raw.objects("participants").stream().anyMatch(p->p.node().equals(audit.object("rawParticipant").node())),"participant_binding");
                require(result.putIfAbsent(id,new Proof(m,receipt.string("requestDigest")))==null,"duplicate_supported_mention");
            }
        }
        return Map.copyOf(result);
    }

    static boolean matches(StrictJson.Obj current, Proof proof) {
        if(proof==null)return false;
        var m=proof.mention();
        if(!m.has("grounding") || !"SUPPORTED".equals(m.object("grounding").string("verdict"))
                || !m.string("articleId").equals(current.string("articleId")) || !m.string("articleVersion").equals(current.string("articleVersion"))
                || !m.string("bodySha256").equals(current.string("bodySha256")))return false;
        Map<String,StrictJson.Obj> accepted=new HashMap<>();m.objects("evidence").forEach(e->accepted.put(e.string("evidenceId"),e));
        if(current.objects("evidence").isEmpty())return false;
        for(var e:current.objects("evidence")) {
            var nativeQuote=accepted.get(e.string("evidenceId"));
            if(nativeQuote==null || e.string("quote").isBlank() || !nativeQuote.string("quote").equals(e.string("quote"))
                    || nativeQuote.count("start")!=e.count("start") || nativeQuote.count("end")!=e.count("end"))return false;
        }
        return true;
    }
    private static void require(boolean condition,String code) {
        if(!condition)throw new IllegalArgumentException("Reference semantic support rejected: "+code);
    }
}
