// 메인 지도 튜토리얼(요구 15·16, design-direction §5.2). 실제 지도 위에서 5단계를 안내한다.
//  ① 기본 조작(이동·확대·화면 맞추기) ② 기업·사건 선택 ③ 관계선 선택 ④ 상세와 근거 확인 ⑤ AI에게 묻기
// - 사용자가 그 동작을 실제로 하면 다음 단계로 넘어간다. [다음]·[튜토리얼 건너뛰기]는 언제나 쓸 수 있다.
// - 대상을 가리는 오버레이를 쓰지 않는다. 패널은 데스크톱에서 왼쪽 목록 자리, 모바일에서 지도 위(문서 흐름 안)에 놓여
//   바텀시트와 겹치지 않는다. 대상은 테두리(.tutorial-target)로 표시하고, 단계 문구는 aria-live로 읽힌다.
// - 끝내거나 건너뛰면 완료로 저장한다(회원은 계정, 비회원은 비회원 세션). 계정 메뉴 [튜토리얼 다시 보기]로 다시 연다.
import { Check, CircleHelp } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { useSearchParams } from "react-router";
import { useSetTutorial } from "@/api/queries";
import { Button } from "@/components/ui/button";
import { ErrorState } from "@/components/ui/feedback";
import { ISOLATED_BUNDLE_ID } from "@/lib/graph-view";
import { cn } from "@/lib/utils";
import { useOverlays } from "./overlays";

interface TutorialStep {
  title: string;
  body: string;
  /** 키보드·스크린리더로 같은 일을 하는 방법 */
  keyboard: string;
  /** 테두리로 표시할 대상(CSS 선택자). match가 있으면 글자가 맞는 요소만. */
  targets: { selector: string; match?: RegExp }[];
  /** 모바일 상세 시트 안에서 보일 한 줄 지시 */
  sheetHint: string;
  /** 지도에서 해야 하는 단계: 시트 안 안내에 [창 닫기]를 둔다 */
  onMap: boolean;
}

const ZOOM_LABELS = ["확대", "축소", "화면에 맞추기"];

const STEPS: TutorialStep[] = [
  {
    title: "지도 움직이기",
    body: "빈 곳을 끌어 지도를 옮기고, 휠이나 두 손가락으로 확대해 보세요. 점선으로 표시한 [화면에 맞추기]를 누르면 전체가 다시 보여요.",
    keyboard: "키보드로는 [확대]·[축소]·[화면에 맞추기] 버튼을 쓸 수 있어요.",
    targets: [{ selector: "[data-graph-canvas]" }, ...ZOOM_LABELS.map((label) => ({ selector: `button[aria-label="${label}"]` }))],
    sheetHint: "지도를 움직이려면 이 창을 닫아요.",
    onMap: true,
  },
  {
    title: "기업이나 사건 고르기",
    body: "기업(동그라미)이나 사건 노드를 눌러 보세요. 무엇과 연결됐는지 상세가 열려요.",
    keyboard: "키보드로는 [목록] 보기에서 기업·사건 행을 Tab으로 골라 Enter를 누르세요.",
    targets: [{ selector: "[data-graph-canvas]" }, { selector: 'button[aria-label="목록으로 보기"]' }],
    sheetHint: "다른 기업·사건을 고르려면 이 창을 닫아요.",
    onMap: true,
  },
  {
    title: "관계선 고르기",
    body: "두 노드를 잇는 선을 눌러 보세요. 어떤 관계인지와 근거 수가 보여요.",
    keyboard: "키보드로는 기업 상세의 [관련 기업] 행을 고르면 그 관계선이 선택돼요.",
    targets: [{ selector: "[data-graph-canvas]" }, { selector: 'aside[aria-label="상세"]' }],
    sheetHint: "관계선을 누르려면 이 창을 닫아요. 기업이면 아래 [관련 기업] 행을 눌러도 돼요.",
    onMap: true,
  },
  {
    title: "상세와 근거 확인하기",
    body: "상세에서 [근거 N건 보기]를 눌러 기사 원문과 인용을 확인해 보세요.",
    keyboard: "상세 패널의 [근거 N건 보기] 버튼으로 Tab해 Enter를 누르세요.",
    targets: [{ selector: "button", match: /근거 \d+건 보기/ }],
    sheetHint: "이 창의 [근거 N건 보기]를 눌러 원문 인용을 확인해 보세요.",
    onMap: false,
  },
  {
    title: "AI에게 묻기",
    body: "상세에서 [AI에게 묻기]를 누르면 고른 대상과 근거를 바탕으로 질문할 수 있어요. 근거가 부족하면 답을 보류해요.",
    keyboard: "상세 패널의 [AI에게 묻기] 버튼으로 Tab해 Enter를 누르세요.",
    targets: [{ selector: "button", match: /AI에게 묻기/ }],
    sheetHint: "이 창의 [AI에게 묻기]를 눌러 보세요.",
    onMap: false,
  },
];

/** 단계마다 대상 요소에 테두리 표시를 붙인다. 대상은 나중에 나타날 수 있으므로 DOM 변화를 따라간다. */
function useTargetOutline(step: TutorialStep | undefined) {
  useEffect(() => {
    if (!step) return;
    let marked: Element[] = [];
    let frame = 0;
    const apply = () => {
      frame = 0;
      const next = step.targets.flatMap(({ selector, match }) =>
        [...document.querySelectorAll(selector)].filter((el) => !el.closest("[data-tutorial-panel]") && (!match || match.test(el.textContent ?? ""))),
      );
      for (const el of marked) if (!next.includes(el)) el.classList.remove("tutorial-target");
      for (const el of next) el.classList.add("tutorial-target");
      marked = next;
    };
    apply();
    const observer = new MutationObserver(() => {
      if (!frame) frame = requestAnimationFrame(apply);
    });
    observer.observe(document.body, { childList: true, subtree: true });
    return () => {
      observer.disconnect();
      cancelAnimationFrame(frame);
      for (const el of marked) el.classList.remove("tutorial-target");
    };
  }, [step]);
}

/** 단계별 '실제로 해 봤는지' 감지. 단계에 들어온 뒤의 변화만 센다. */
function useStepDone(index: number, active: boolean) {
  const [params] = useSearchParams();
  const { evidenceOpen, chatOpen } = useOverlays();
  const select = params.get("select") ?? "";
  const startSelect = useRef(select);
  const [done, setDone] = useState(false);

  useEffect(() => {
    startSelect.current = select;
    setDone(false);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [index, active]);

  // ① 기본 조작: 확대·축소·맞추기 버튼, 캔버스 휠, 캔버스 끌기
  useEffect(() => {
    if (!active || index !== 0) return;
    let start: { x: number; y: number } | null = null;
    const onCanvas = (target: EventTarget | null) => target instanceof Element && target.closest("[data-graph-canvas]");
    const onClick = (e: MouseEvent) => {
      const button = e.target instanceof Element ? e.target.closest("button") : null;
      if (button && ZOOM_LABELS.includes(button.getAttribute("aria-label") ?? "")) setDone(true);
    };
    const onWheel = (e: WheelEvent) => onCanvas(e.target) && setDone(true);
    const onDown = (e: PointerEvent) => (start = onCanvas(e.target) ? { x: e.clientX, y: e.clientY } : null);
    const onMove = (e: PointerEvent) => start && Math.hypot(e.clientX - start.x, e.clientY - start.y) > 12 && setDone(true);
    const onUp = () => (start = null);
    document.addEventListener("click", onClick, true);
    document.addEventListener("wheel", onWheel, { capture: true, passive: true });
    document.addEventListener("pointerdown", onDown, true);
    document.addEventListener("pointermove", onMove, true);
    document.addEventListener("pointerup", onUp, true);
    return () => {
      document.removeEventListener("click", onClick, true);
      document.removeEventListener("wheel", onWheel, true);
      document.removeEventListener("pointerdown", onDown, true);
      document.removeEventListener("pointermove", onMove, true);
      document.removeEventListener("pointerup", onUp, true);
    };
  }, [index, active]);

  const changed = select !== startSelect.current;
  const derived =
    (index === 1 && changed && select.startsWith("node:") && select !== `node:${ISOLATED_BUNDLE_ID}`) ||
    (index === 2 && changed && select.startsWith("edge:")) ||
    (index === 3 && evidenceOpen) ||
    (index === 4 && chatOpen);
  return active && (done || derived);
}

/** 튜토리얼 진행 상태. 패널(지도 위)과 시트 안 안내가 같은 상태를 나눠 쓴다. */
export interface GraphTutorialState {
  index: number;
  step: TutorialStep;
  last: boolean;
  /** 단계마다 사용자가 직접 해 봤는지 */
  practiced: boolean[];
  saving: boolean;
  saveError: Error | null;
  /** 완료(또는 건너뛰기)를 저장하고 닫는다 */
  finish: () => void;
  previous: () => void;
  next: () => void;
}

/** active=false면 대상 표시·동작 감지를 멈춘다. 다시 켜지면(다시 보기) 1단계부터 시작한다. */
export function useGraphTutorial(active: boolean, onClose: () => void): GraphTutorialState {
  const [index, setIndex] = useState(0);
  const [practiced, setPracticed] = useState<boolean[]>(() => STEPS.map(() => false));
  const save = useSetTutorial();
  const step = STEPS[index] ?? STEPS[0]!;
  const done = useStepDone(index, active);
  const last = index === STEPS.length - 1;
  useTargetOutline(active ? step : undefined);
  useEffect(() => {
    if (!active) return;
    setIndex(0);
    setPracticed(STEPS.map(() => false));
  }, [active]);

  const finish = () => save.mutate(true, { onSuccess: onClose });

  // 해 보면 다음 단계로(마지막 단계는 완료 저장).
  useEffect(() => {
    if (!done || practiced[index]) return;
    setPracticed((prev) => prev.map((v, i) => (i === index ? true : v)));
    if (last) finish();
    else setIndex(index + 1);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [done]);

  return {
    index,
    saving: save.isPending,
    saveError: save.error,
    step,
    last,
    practiced,
    finish,
    previous: () => setIndex(Math.max(0, index - 1)),
    next: () => (last ? finish() : setIndex(index + 1)),
  };
}

function TutorialActions({ tutorial, compact }: { tutorial: GraphTutorialState; compact?: boolean }) {
  const { index, last, saving, finish, previous, next } = tutorial;
  return (
    <div className="flex flex-wrap items-center gap-2">
      {index > 0 && !compact && (
        <Button variant="secondary" size="sm" onClick={previous}>
          이전
        </Button>
      )}
      <Button size="sm" loading={saving && last} onClick={next}>
        {last ? "마치기" : "다음"}
      </Button>
      <Button variant="ghost" size="sm" className="ml-auto" loading={saving && !last} onClick={finish}>
        튜토리얼 건너뛰기
      </Button>
    </div>
  );
}

/** 지도 위(데스크톱은 왼쪽 목록 자리, 모바일은 지도 위 흐름 안) 튜토리얼 패널.
 *  live=false면 단계 알림을 읽지 않는다(모바일에서 시트 안 안내가 대신 읽을 때). */
export function GraphTutorialPanel({ tutorial, live = true, className }: { tutorial: GraphTutorialState; live?: boolean; className?: string }) {
  const { index, step, practiced, saveError, finish } = tutorial;
  const headingRef = useRef<HTMLHeadingElement>(null);
  // 처음 열리면 패널 제목으로 포커스를 옮겨 스크린리더가 튜토리얼 시작을 읽게 한다.
  useEffect(() => {
    headingRef.current?.focus({ preventScroll: true });
  }, []);
  const previousPracticed = index > 0 && practiced[index - 1];

  return (
    <section
      data-tutorial-panel=""
      aria-labelledby="tutorial-title"
      className={cn("flex flex-col gap-3 rounded-md border border-border-strong bg-surface-raised p-4", className)}
    >
      <div className="flex items-center gap-2 text-sm font-semibold text-brand-primary">
        <CircleHelp className="size-4" aria-hidden="true" />
        <span>
          튜토리얼 <span className="tabular-nums">{index + 1}/{STEPS.length}</span>
        </span>
      </div>
      <h2 id="tutorial-title" ref={headingRef} tabIndex={-1} className="text-lg leading-snug font-semibold text-text-primary outline-none">
        {step.title}
      </h2>
      <div aria-live={live ? "polite" : "off"} className="flex flex-col gap-2">
        {previousPracticed && (
          <p className="flex items-center gap-1.5 text-sm font-medium text-brand-primary">
            <Check className="size-4" aria-hidden="true" />
            {STEPS[index - 1]?.title}: 해 봤어요
          </p>
        )}
        <p className="text-base text-text-primary">{step.body}</p>
        <p className="text-sm text-text-secondary">{step.keyboard}</p>
      </div>
      <ol className="flex gap-1.5" aria-label="진행 단계">
        {STEPS.map((s, i) => (
          <li key={s.title} className={cn("h-1.5 flex-1 rounded-full", i < index ? "bg-brand-primary" : i === index ? "bg-text-secondary" : "bg-surface-sunken")}>
            <span className="sr-only">
              {i + 1}단계 {s.title}
              {practiced[i] ? ", 해 봄" : ""}
              {i === index ? ", 지금 단계" : ""}
            </span>
          </li>
        ))}
      </ol>
      {saveError && <ErrorState error={saveError} title="튜토리얼 완료를 저장하지 못했어요" onRetry={finish} compact />}
      <TutorialActions tutorial={tutorial} />
    </section>
  );
}

/** 모바일 상세 시트 안(헤더 아래)의 짧은 안내. 시트가 열린 동안 지도 위 패널은 시트 뒤에 가려지므로
 *  단계 번호·한 줄 지시·[다음]/[건너뛰기]를 여기서 보인다. 지도에서 해야 하는 단계는 [창 닫기]로 바로 돌아간다. */
export function GraphTutorialSheetBar({ tutorial, onCloseSheet }: { tutorial: GraphTutorialState; onCloseSheet: () => void }) {
  const { index, step, saveError, finish } = tutorial;
  // 시트가 열릴 때 지도 위 패널은 시트 뒤로 숨겨지고(aria-hidden) 단계 알림도 끈다. 여기서 한 번만 읽는다:
  // 처음에는 비운 알림 영역에 마운트 뒤 문구를 넣어야 스크린리더가 읽는다.
  const message = `튜토리얼 ${index + 1}/${STEPS.length} ${step.title}. ${step.sheetHint}`;
  const [spoken, setSpoken] = useState("");
  useEffect(() => setSpoken(message), [message]);
  return (
    <section data-tutorial-panel="" aria-label="튜토리얼" className="mb-2 flex flex-col gap-2 rounded-md border border-border-strong bg-surface-raised px-3 py-2">
      <p aria-live="polite" className="sr-only">
        {spoken}
      </p>
      <p aria-hidden="true" className="text-sm text-text-primary">
        <span className="font-semibold text-brand-primary">
          튜토리얼 <span className="tabular-nums">{index + 1}/{STEPS.length}</span> · {step.title}
        </span>
        <br />
        {step.sheetHint}
      </p>
      {saveError && <ErrorState error={saveError} title="튜토리얼 완료를 저장하지 못했어요" onRetry={finish} compact />}
      <div className="flex flex-wrap items-center gap-2">
        {step.onMap && (
          <Button variant="secondary" size="sm" onClick={onCloseSheet}>
            창 닫기
          </Button>
        )}
        <div className="ml-auto flex items-center gap-2">
          <TutorialActions tutorial={tutorial} compact />
        </div>
      </div>
    </section>
  );
}
