package com.zoop.briefing.replay;

import com.zoop.common.json.StrictJson;
import java.util.ArrayList;
import java.util.HashMap;
import java.util.HashSet;
import java.util.List;
import java.util.Map;
import java.util.Set;
import tools.jackson.databind.node.ArrayNode;
import tools.jackson.databind.node.ObjectNode;

/** Identity/extractive guards, followed by independent semantic checks; no fact certification. */
final class BriefingMarketGroundingRules {
    static final String VERSION = "market-context-v3-grounded";
    static boolean version(String value) { return Set.of("market-context-v2.6-outlook", "market-context-v2.7-outlook", "market-context-v2.8-outlook", "market-context-v2.9-outlook", VERSION).contains(value); }
    static boolean strictVersion(String value) { return Set.of("market-context-v2.7-outlook", "market-context-v2.8-outlook", "market-context-v2.9-outlook", VERSION).contains(value); }
    static boolean extractiveVersion(String value) { return Set.of("market-context-v2.9-outlook", VERSION).contains(value); }
    static final List<String> FLAGS;
    static {
        var flags = new ArrayList<>(BriefingMarketContextRules.ROLE_FLAGS);
        flags.addAll(List.of("factPlanCoverage", "scopePreserved", "koreanOnly")); FLAGS = List.copyOf(flags);
    }
    private BriefingMarketGroundingRules() { }

    static void validatePlan(StrictJson.Obj plan, StrictJson.Obj news, StrictJson.Obj broad) { validatePlan(plan, news, broad, false); }
    static void validatePlan(StrictJson.Obj plan, StrictJson.Obj news, StrictJson.Obj broad, boolean translated) { validatePlan(plan, news, broad, translated, false); }
    static void validatePlan(StrictJson.Obj plan, StrictJson.Obj news, StrictJson.Obj broad, boolean translated, boolean extractive) {
        plan.exactly(Set.of("facts")); var facts = plan.objects("facts");
        check(!facts.isEmpty() && facts.size() <= 3, "market_fact_plan_shape");
        if (extractive) {
            Map<String, String> owners = new HashMap<>();
            for (StrictJson.Obj item : news.objects("selected")) for (StrictJson.Obj source : item.objects("sources")) owners.put(source.string("evidenceId"), source.string("documentId"));
            for (StrictJson.Obj doc : broad.objects("documents")) for (StrictJson.Obj source : doc.objects("sources")) owners.put(source.string("evidenceId"), doc.string("documentId"));
            for (StrictJson.Obj fact : facts) {
                fact.exactly(Set.of("text", "sourceIds", "factType")); check(Set.of("revenue", "operating_profit", "net_profit", "launch", "plan", "other").contains(fact.string("factType")), "market_fact_fields"); var ids = fact.strings("sourceIds"); Set<String> docs = new HashSet<>();
                check(!ids.isEmpty() && ids.size() <= 2 && ids.size() == new HashSet<>(ids).size(), "market_fact_source_identity");
                for (String id : ids) { check(owners.containsKey(id), "market_fact_source_identity"); docs.add(owners.get(id)); }
                check(docs.size() == 1 && !docs.contains(null) && !docs.contains(""), "market_fact_source_owner");
                String text = fact.string("text"); check(List.of("매출", "영업이익", "순이익").stream().filter(text::contains).count() <= 1, "market_fact_multiple_metrics"); language(text);
            }
            return;
        }
        Map<String, String> quotes = new HashMap<>();
        for (StrictJson.Obj item : news.objects("selected")) for (StrictJson.Obj source : item.objects("sources")) quotes.put(source.string("evidenceId"), source.string("quote"));
        for (StrictJson.Obj doc : broad.objects("documents")) for (StrictJson.Obj source : doc.objects("sources")) quotes.put(source.string("evidenceId"), source.string("quote"));
        Set<String> seen = new HashSet<>();
        for (StrictJson.Obj fact : facts) {
            fact.exactly(Set.of("text", "evidenceId", "sourceQuote", "subject", "metric", "period", "qualifiers"));
            String quote = fact.string("sourceQuote"), text = fact.string("text");
            int length = quote.codePointCount(0, quote.length());
            check(quotes.containsKey(fact.string("evidenceId")) && length >= 12 && length <= 350
                    && quotes.get(fact.string("evidenceId")).contains(quote), "market_fact_exact_quote");
            check(!fact.string("subject").isBlank() && !fact.string("metric").isBlank()
                    && quote.contains(fact.string("subject")) && quote.contains(fact.string("metric")), "market_fact_subject_metric");
            check(List.of("매출", "영업이익", "순이익").stream().filter(text::contains).count() <= 1, "market_fact_multiple_metrics");
            if (translated) for (StrictJson.Obj qualifier : fact.objects("qualifiers")) {
                qualifier.exactly(Set.of("sourceText", "renderedText"));
                check(!qualifier.string("sourceText").isEmpty() && !qualifier.string("renderedText").isEmpty()
                    && quote.contains(qualifier.string("sourceText")) && text.contains(qualifier.string("renderedText")), "market_fact_qualifier");
            } else for (String qualifier : fact.strings("qualifiers")) check(!qualifier.isEmpty() && quote.contains(qualifier) && text.contains(qualifier), "market_fact_qualifier");
            check(seen.add(fact.string("evidenceId") + "\n" + text), "market_fact_duplicate"); language(text);
        }
    }

    /** The planning response owns factual text; the second response owns analytical text. */
    static ArrayNode project(ArrayNode analysis, StrictJson.Obj plan) { return project(analysis, plan, false); }
    static ArrayNode project(ArrayNode analysis, StrictJson.Obj plan, boolean unique) {
        ArrayNode result = StrictJson.newArray(); var facts = plan.objects("facts");
        Map<String, Set<String>> refs = new HashMap<>();
        for (int i = 0; i < facts.size(); i++) {
            StrictJson.Obj fact = facts.get(i); String id = "fact:" + i; var sources = fact.has("sourceIds") ? fact.strings("sourceIds") : List.of(fact.string("evidenceId")); refs.put(id, Set.copyOf(sources));
            ObjectNode claim = StrictJson.newObject().put("kind", "fact").put("text", fact.string("text"));
            var evidence = claim.putArray("evidenceIds"); sources.forEach(evidence::add);
            for (String key : List.of("indicatorIds", "previousForecastIds", "previousPublicationIds", "evaluationIds", "conditions", "counterFactors")) claim.putArray(key);
            for (String key : List.of("targetId", "direction", "updateAction")) claim.putNull(key);
            claim.putArray("basisFactIds").add(id); result.add(claim);
        }
        for (var node : analysis) {
            StrictJson.Obj claim = StrictJson.Obj.of(node); check(!"fact".equals(claim.string("kind")), "market_fact_rewrite_forbidden");
            List<String> ids = claim.strings("basisFactIds"); Set<String> expected = new HashSet<>();
            check(!ids.isEmpty() && ids.size() == new HashSet<>(ids).size(), "market_analysis_foreign_fact");
            for (String id : ids) { check(refs.containsKey(id), "market_analysis_foreign_fact"); expected.addAll(refs.get(id)); }
            check(expected.equals(new HashSet<>(claim.strings("evidenceIds"))), "market_analysis_fact_evidence");
            language(claim.string("text")); claim.strings("counterFactors").forEach(BriefingMarketGroundingRules::language);
            result.add(node.deepCopy());
        }
        if (unique) {
            Set<String> texts = new HashSet<>(), targets = new HashSet<>();
            for (var node : result) {
                StrictJson.Obj claim = StrictJson.Obj.of(node);
                check(texts.add(claim.string("text")), "market_grounding_duplicate_claim");
                if ("forecast".equals(claim.string("kind"))) check(targets.add(claim.string("targetId")), "market_grounding_duplicate_target");
            }
        }
        return result;
    }

    static ObjectNode modelView(StrictJson.Obj frozen, StrictJson.Obj plan) {
        StrictJson.Obj context = frozen.object("marketContext"); var view = StrictJson.newObject();
        var round = view.putObject("round"); for (String key : List.of("roundId","date","edition","window")) round.set(key, context.raw(key).deepCopy());
        view.set("coverage", context.object("coverage").node().deepCopy());
        Map<String, tools.jackson.databind.JsonNode> sources = new HashMap<>();
        for (StrictJson.Obj item : frozen.objects("selected")) for (StrictJson.Obj source : item.objects("sources")) sources.put(source.string("evidenceId"), source.node());
        for (StrictJson.Obj doc : context.objects("documents")) for (StrictJson.Obj source : doc.objects("sources")) sources.put(source.string("evidenceId"), source.node());
        Set<String> ids = new java.util.TreeSet<>(); for (StrictJson.Obj fact : plan.objects("facts")) ids.addAll(fact.strings("sourceIds"));
        var selected = view.putObject("sources"); for (String id : ids) { check(sources.containsKey(id), "model_view_source_missing"); selected.set(id, sources.get(id).deepCopy()); }
        view.set("marketSnapshot", frozen.object("marketSnapshot").node().deepCopy());
        for (String key : List.of("forecastTargets","forecastEvaluations")) view.set(key, context.array(key).deepCopy());
        var previous = (ObjectNode) context.object("previousPublication").node().deepCopy();
        if ("available".equals(context.object("previousPublication").string("status"))) {
            var original = context.object("previousPublication").object("summary"); var summary = StrictJson.newObject();
            for (String key : List.of("text","resultVersion","forecasts")) if (original.has(key)) summary.set(key,original.raw(key).deepCopy());
            previous.set("summary",summary);
        }
        view.set("previousPublication",previous); view.set("claimRequirements",frozen.object("claimRequirements").node().deepCopy()); view.put("scopeNote",frozen.string("scopeNote")); return view;
    }

    private static void language(String text) { check(!text.matches("(?s).*[\u3040-\u30ff].*"), "market_grounding_foreign_language"); }
    private static void check(boolean condition, String reason) { if (!condition) throw new IllegalArgumentException("market_context_" + reason); }
}
