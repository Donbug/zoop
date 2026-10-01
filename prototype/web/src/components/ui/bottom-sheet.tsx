import * as DialogPrimitive from "@radix-ui/react-dialog";
import { useRef, useState, type KeyboardEvent, type PointerEvent, type ReactNode } from "react";
import { cn } from "@/lib/utils";
import { OverlayHeader, overlayScrimClass, useFocusReturn } from "./overlay-parts";

export type SheetSnap = "half" | "full";

/** 시트는 늘 90dvh 높이로 두고, 50% 스냅은 아래로 40dvh 내린다(높이 대신 translate로 움직여 레이아웃을 다시 계산하지 않는다). */
const sheetHeight = "90dvh";
const snapOffset: Record<SheetSnap, string> = { half: "40dvh", full: "0px" };
/** 이 거리(px) 이상 끌면 다음 스냅으로 옮긴다. */
const dragThreshold = 64;

export interface BottomSheetProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  title: ReactNode;
  description?: ReactNode;
  /** 닫기 버튼의 스크린리더 이름 (예: "근거 창 닫기") */
  closeLabel?: string;
  headerExtra?: ReactNode;
  children: ReactNode;
  footer?: ReactNode;
  /** 제어형 스냅. 주지 않으면 defaultSnap에서 시작해 내부에서 관리한다. */
  snap?: SheetSnap;
  defaultSnap?: SheetSnap;
  onSnapChange?: (snap: SheetSnap) => void;
  className?: string;
}

/**
 * 모바일 바텀시트. 스냅 50%/90%, 상단 손잡이.
 * - 손잡이를 위로 끌면 90%, 아래로 끌면 50% → 한 번 더 내리면 닫힘
 * - 손잡이에 포커스하고 Enter/Space로 50%↔90%, ↑/↓로 크기 조절, Esc로 닫기
 * - 열리면 포커스를 시트 안에 가두고, 닫히면 열기 전 요소로 되돌린다. 배경(딤)을 누르면 닫힌다.
 * - 동작 줄이기 설정이면 크기 전환 애니메이션이 없다(전역 규칙).
 */
export function BottomSheet({
  open,
  onOpenChange,
  title,
  description,
  closeLabel,
  headerExtra,
  children,
  footer,
  snap: snapProp,
  defaultSnap = "half",
  onSnapChange,
  className,
}: BottomSheetProps) {
  const focus = useFocusReturn();
  const [innerSnap, setInnerSnap] = useState<SheetSnap>(defaultSnap);
  const snap = snapProp ?? innerSnap;
  const [dragY, setDragY] = useState<number | null>(null);
  const startY = useRef(0);
  const dragged = useRef(false);

  const changeSnap = (next: SheetSnap) => {
    if (snapProp === undefined) setInnerSnap(next);
    onSnapChange?.(next);
  };
  const handleOpenChange = (next: boolean) => {
    // 다음에 열 때는 기본 스냅에서 시작한다.
    if (!next && snapProp === undefined) setInnerSnap(defaultSnap);
    onOpenChange(next);
  };

  const onPointerDown = (event: PointerEvent<HTMLButtonElement>) => {
    event.currentTarget.setPointerCapture(event.pointerId);
    startY.current = event.clientY;
    dragged.current = false;
    setDragY(0);
  };
  const onPointerMove = (event: PointerEvent<HTMLButtonElement>) => {
    if (dragY === null) return;
    setDragY(event.clientY - startY.current);
  };
  const onPointerUp = () => {
    if (dragY === null) return;
    const dy = dragY;
    setDragY(null);
    dragged.current = Math.abs(dy) > 4;
    if (dy <= -dragThreshold) changeSnap("full");
    else if (dy >= dragThreshold) {
      if (snap === "full") changeSnap("half");
      else handleOpenChange(false);
    }
  };
  const onHandleKeyDown = (event: KeyboardEvent<HTMLButtonElement>) => {
    if (event.key === "ArrowUp") {
      event.preventDefault();
      changeSnap("full");
    } else if (event.key === "ArrowDown") {
      event.preventDefault();
      changeSnap("half");
    }
  };

  // 진입·퇴장 키프레임은 transform을 쓰므로 스냅 위치는 별도 속성인 translate로 준다(둘이 합성된다).
  const offset = snapOffset[snap];
  const translate = dragY === null ? `0 ${offset}` : `0 max(0px, calc(${offset} + ${dragY}px))`;
  // 화면 밖으로 내려간 만큼 아래 여백을 둬서 50% 스냅에서도 본문 끝과 footer가 보이게 한다.
  const paddingBottom = `calc(${offset} + env(safe-area-inset-bottom))`;

  return (
    <DialogPrimitive.Root open={open} onOpenChange={handleOpenChange}>
      <DialogPrimitive.Portal>
        <DialogPrimitive.Overlay className={overlayScrimClass} />
        <DialogPrimitive.Content
          {...focus}
          data-snap={snap}
          style={{ height: sheetHeight, translate, paddingBottom }}
          className={cn(
            "fixed inset-x-0 bottom-0 z-50 flex flex-col rounded-t-lg bg-surface-overlay shadow-modal",
            "motion-sheet-bottom outline-none",
            dragY === null && "transition-[translate] duration-(--zoop-motion-duration-normal) ease-standard",
            className,
          )}
        >
          <button
            type="button"
            aria-label={snap === "half" ? "시트 크게 보기" : "시트 작게 보기"}
            onClick={() => {
              // 끌기가 끝난 직후의 click은 무시한다(스냅은 onPointerUp에서 이미 정했다).
              if (dragged.current) {
                dragged.current = false;
                return;
              }
              changeSnap(snap === "half" ? "full" : "half");
            }}
            onKeyDown={onHandleKeyDown}
            onPointerDown={onPointerDown}
            onPointerMove={onPointerMove}
            onPointerUp={onPointerUp}
            onPointerCancel={() => setDragY(null)}
            className="relative flex h-6 w-full shrink-0 cursor-grab touch-none items-end justify-center rounded-t-lg after:absolute after:inset-x-0 after:-top-2.5 after:-bottom-2.5 after:content-[''] focus-visible:-outline-offset-2 active:cursor-grabbing"
          >
            <span className="h-1 w-9 rounded-full bg-border-strong" aria-hidden="true" />
          </button>
          <OverlayHeader title={title} description={description} closeLabel={closeLabel} headerExtra={headerExtra} className="pt-2" />
          <div className="min-h-0 flex-1 overflow-y-auto overscroll-contain px-4 py-4">{children}</div>
          {footer && <div className="border-t border-border-subtle px-4 py-3">{footer}</div>}
        </DialogPrimitive.Content>
      </DialogPrimitive.Portal>
    </DialogPrimitive.Root>
  );
}
