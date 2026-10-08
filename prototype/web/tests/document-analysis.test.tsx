import { screen, within } from "@testing-library/react";
import { describe, expect, test } from "vitest";
import type { Schemas } from "@/api/client";
import { openApp } from "./support/app";
import { json } from "./support/fake-bff";
import { ALPHA, BETA, metadata, type TestCompany } from "./support/fixtures";
import { pageOf } from "./support/routes";

const title = "가상 두 기업의 공급 계약";
const quote = "알파전자는 공급 계약을 맺었고 베타화학은 원가가 늘었다.";
const provenance: Schemas["AnalysisSummary"]["provenance"] = { sourceKind: "synthetic", executionMode: "replay", recordingKind: "authored-test" };
const summary: Schemas["AnalysisSummary"] = {
  schemaVersion: "zoop-ai-s1-1", artifactId: "summary-1", documentId: "doc-1", documentVersion: "dv-1", resultVersion: "summary-v1",
  text: "가상 공급 계약을 체결했어요.", claims: [
    { claimId: "claim-1", text: "가상 공급 계약을 체결했어요.", assertionKind: "fact", evidenceIds: ["quote-1"] },
    { claimId: "claim-limit", text: "계약 금액은 제시되지 않았어요.", assertionKind: "limitation", evidenceIds: ["quote-1"] },
  ],
  citations: [{ evidenceId: "quote-1", documentId: "doc-1", documentVersion: "dv-1", textArtifactId: "text-1", offsetUnit: "unicode_code_point", start: 0, end: Array.from(quote).length, quote, inputKind: "body", rawLocatorIds: ["raw-1"] }],
  limitations: ["계약 금액은 제시되지 않았어요."], producedAt: "2026-10-02T09:00:00+09:00", provenance,
};
function documentFor(company: TestCompany): Schemas["CompanyDocument"] {
  return {
    id: "doc-1", title, publisher: "가상일보", url: null, publishedAt: metadata.asOf, synthetic: true, events: [], quotes: [],
    sentiment: { label: company.id === ALPHA.id ? "positive" : "negative", rationale: `${company.name}의 계약 영향이에요.`, quotes: [quote], judgedAt: metadata.asOf, model: "replay-test", promptVersion: "test-1", companyId: company.id },
    documentSummary: summary, documentVersion: "dv-1", resultVersion: "summary-v1", analysisProvenance: provenance,
    analysisStatus: { summary: { status: "available", reason: null }, sentiment: { status: "available", reason: null } },
  };
}
function evidenceFor(company: TestCompany): Schemas["EvidenceResponse"] {
  const doc = documentFor(company);
  return {
    id: "quote-1", quote, quoteVerified: true, start: 0, end: Array.from(quote).length, articleId: doc.id, articleVersion: "dv-1",
    article: { title, publisher: doc.publisher, url: null, publishedAt: doc.publishedAt, synthetic: true }, eventIds: [], metadata,
    sentiment: doc.sentiment, documentSummary: summary, documentVersion: "dv-1", resultVersion: "summary-v1", analysisProvenance: provenance, analysisStatus: doc.analysisStatus,
  };
}
function openDocuments(transform: (doc: Schemas["CompanyDocument"]) => Schemas["CompanyDocument"] = (doc) => doc) {
  return openApp(pageOf(ALPHA, "?tab=documents"), (bff) => {
    bff.on("GET", "/api/companies/:id/documents", (_, { id }) => json({ items: [transform(documentFor(id === BETA.id ? BETA : ALPHA))], metadata }));
    bff.on("GET", "/api/evidence/:id", (request) => json(evidenceFor(request.query.get("companyId") === BETA.id ? BETA : ALPHA)));
  });
}

describe("저장된 문서 요약과 기업별 판정", () => {
  test("두 기업의 같은 문서는 상반 판정이며 요약 근거는 정확한 기업과 문서 버전으로 열린다; 쓰기는 없다", async () => {
    const app = await openDocuments();
    await screen.findByRole("button", { name: `${ALPHA.id} · ${title} · 긍정 판정 근거 보기` });
    expect(screen.getAllByText("AI 문서 요약")).toHaveLength(1);
    expect(screen.getByText(/데모 예시/)).toBeTruthy();
    await app.user.click(screen.getByRole("button", { name: "요약 1 근거 보기" }));
    const dialog = within(await screen.findByRole("dialog", { name: "근거 문서" }));
    expect(await dialog.findByText(`“${quote}”`)).toBeTruthy();
    expect(app.bff.calls("GET", "/api/evidence/quote-1")[0]?.query.get("companyId")).toBe(ALPHA.id);
    await app.user.keyboard("{Escape}");
    await app.navigate(pageOf(BETA, "?tab=documents"));
    await screen.findByRole("button", { name: `${BETA.id} · ${title} · 부정 판정 근거 보기` });
    expect(screen.queryByRole("button", { name: /긍정 판정 근거 보기/ })).toBeNull();
    expect(app.bff.writes).toEqual([]);
  });

  test("검증된 limitation claim은 한 번만 표시하고 claim에 없는 limitation 본문은 공개하지 않는다", async () => {
    const limitationClaim = summary.claims.find((claim) => claim.assertionKind === "limitation")!;
    const orphan = `${limitationClaim.claimId}: claim으로 검증되지 않은 별도 내용`;
    await openDocuments((doc) => ({ ...doc, documentSummary: { ...summary, limitations: [...summary.limitations, orphan] } }));
    const region = within(await screen.findByRole("region", { name: `${ALPHA.id} · ${title} AI 문서 요약` }));
    expect(region.getAllByText((text) => text.includes(limitationClaim.text))).toHaveLength(1);
    expect(region.queryByText((text) => text.includes(orphan))).toBeNull();
  });

  test.each(["not_requested", "pending"] as const)("%s와 null은 가짜 판단 보류나 준비 중을 표시하지 않는다", async (status) => {
    await openDocuments((doc) => ({ ...doc, documentSummary: null, sentiment: null, analysisStatus: { summary: { status, reason: null }, sentiment: { status, reason: null } } }));
    await screen.findByRole("heading", { name: title });
    expect(screen.queryByText(/AI 문서 요약|판단 보류|준비 중|데모 예시/)).toBeNull();
  });

  test.each(["failed", "withheld"] as const)("%s는 제목·출처를 유지하고 보호 분석 본문을 그리지 않는다", async (status) => {
    await openDocuments((doc) => ({ ...doc, analysisStatus: { summary: { status, reason: "private-detail" }, sentiment: { status, reason: "private-detail" } } }));
    await screen.findByRole("heading", { name: title });
    expect(screen.getByText("가상일보")).toBeTruthy();
    expect(screen.queryByText(summary.text)).toBeNull();
    expect(screen.queryByText(/private-detail|데모 예시/)).toBeNull();
    expect(screen.queryByRole("button", { name: /판정 근거 보기/ })).toBeNull();
    expect(screen.getByText(status === "failed" ? "문서 요약을 만들지 못했어요." : "문서 요약은 지금 제공하지 않아요.")).toBeTruthy();
  });

  test("실제 기사에는 authored 합성 replay 결과를 붙이지 않는다", async () => {
    await openDocuments((doc) => ({ ...doc, synthetic: false }));
    await screen.findByRole("heading", { name: title });
    expect(screen.queryByText(summary.text)).toBeNull();
    expect(screen.queryByRole("button", { name: /판정 근거 보기/ })).toBeNull();
  });

  test("같은 문서의 여러 인용은 요약을 한 번만 보여주며 요약 출처 인용을 전문으로 부르지 않는다", async () => {
    const app = await openDocuments((doc) => ({ ...doc, documentSummary: { ...summary, claims: [{ ...summary.claims[0]!, evidenceIds: ["quote-1", "quote-2"] }, ...summary.claims.filter((claim) => claim.assertionKind === "limitation")] } }));
    app.bff.on("GET", "/api/evidence/:id", (_, { id }) => json({
      ...evidenceFor(ALPHA), id,
      documentSummary: { ...summary, citations: [{ ...summary.citations[0]!, evidenceId: id!, inputKind: "summary" }] },
    }));
    await app.user.click(await screen.findByRole("button", { name: "요약 1 근거 보기" }));
    const dialog = within(await screen.findByRole("dialog", { name: "근거 문서" }));
    await dialog.findAllByText(`“${quote}”`);
    expect(dialog.getAllByText("AI 문서 요약")).toHaveLength(1);
    expect(dialog.getAllByText("제공된 요약에서 인용했어요. 기사 전문 인용은 아니에요.")).toHaveLength(2);
  });

  test("클릭 당시 요약 버전과 다른 근거 응답은 인용을 노출하지 않는다", async () => {
    const app = await openDocuments();
    app.bff.on("GET", "/api/evidence/:id", json({ ...evidenceFor(ALPHA), documentSummary: { ...summary, resultVersion: "summary-v2" } }));
    await app.user.click(await screen.findByRole("button", { name: "요약 1 근거 보기" }));
    const dialog = within(await screen.findByRole("dialog", { name: "근거 문서" }));
    await dialog.findByText(/근거 1건은 삭제됐거나 지금 볼 수 없는 자료예요/);
    expect(dialog.queryByText(`“${quote}”`)).toBeNull();
    expect(dialog.queryByText(summary.text)).toBeNull();
  });

  test("유효한 undetermined는 null과 달리 판단 보류 사유를 보여준다", async () => {
    const app = await openDocuments((doc) => ({ ...doc, sentiment: { ...doc.sentiment!, label: "undetermined", rationale: "방향을 판단할 근거가 부족해요." } }));
    await app.user.click(await screen.findByRole("button", { name: /판단 보류 판정 근거 보기/ }));
    expect(await screen.findByText("방향을 판단할 근거가 부족해요.")).toBeTruthy();
    expect(app.bff.writes).toEqual([]);
  });

  test("늦은 A 근거 응답도 B 문맥의 인용과 판정을 덮지 않는다", async () => {
    const app = await openDocuments();
    const held = app.bff.holdResponse("GET", "/api/evidence/:id", (request) => request.query.get("companyId") === ALPHA.id);
    await app.user.click(await screen.findByRole("button", { name: "요약 1 근거 보기" }));
    await held.arrived();
    await app.user.keyboard("{Escape}");
    await app.navigate(pageOf(BETA, "?tab=documents"));
    await screen.findByRole("button", { name: /부정 판정 근거 보기/ });
    await app.user.click(screen.getByRole("button", { name: "요약 1 근거 보기" }));
    const dialog = within(await screen.findByRole("dialog", { name: "근거 문서" }));
    await dialog.findByRole("button", { name: /부정 판정 근거 보기/ });
    held.respond();
    await app.settle();
    expect(dialog.queryByRole("button", { name: /긍정 판정 근거 보기/ })).toBeNull();
    expect(app.bff.calls("GET", "/api/evidence/quote-1").at(-1)?.query.get("companyId")).toBe(BETA.id);
    expect(app.bff.writes).toEqual([]);
  });

  test("늦은 A 문서 응답은 B의 판정을 덮지 않는다", async () => {
    const app = await openApp(pageOf(ALPHA, "?tab=documents"), (bff) => {
      bff.on("GET", "/api/companies/:id/documents", (_, { id }) => json({ items: [documentFor(id === BETA.id ? BETA : ALPHA)], metadata }));
      return bff.holdResponse("GET", "/api/companies/:id/documents", (request) => request.path.includes(encodeURIComponent(ALPHA.id)));
    });
    await app.held.arrived();
    await app.navigate(pageOf(BETA, "?tab=documents"));
    await screen.findByRole("button", { name: /부정 판정 근거 보기/ });
    app.held.respond();
    await app.settle();
    expect(screen.queryByRole("button", { name: /긍정 판정 근거 보기/ })).toBeNull();
    expect(app.bff.writes).toEqual([]);
  });
});
