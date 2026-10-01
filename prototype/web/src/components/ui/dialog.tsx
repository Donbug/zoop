import * as DialogPrimitive from "@radix-ui/react-dialog";
import type { ReactNode } from "react";
import { useMediaQuery } from "@/lib/theme";
import { cn } from "@/lib/utils";
import { BottomSheet, type SheetSnap } from "./bottom-sheet";
import { OverlayHeader, overlayScrimClass, useFocusReturn } from "./overlay-parts";

// Dialog(가운데 창)와 Sheet(데스크톱 오른쪽 / 모바일 바텀시트)는 같은 Radix Dialog 위에 만든다.
// - 열리면 role="dialog" + aria-modal, 배경 스크롤 잠금, 포커스 가두기
// - Esc 또는 [닫기]로 닫히고, 열기 직전에 포커스가 있던 요소로 포커스를 되돌린다(NFR-12)
// - 떠 있는 표면은 16px 모서리 + 그림자만(테두리 없음)

interface OverlayWindowProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  title: ReactNode;
  description?: ReactNode;
  /** 닫기 버튼의 스크린리더 이름 (예: "근거 창 닫기") */
  closeLabel?: string;
  headerExtra?: ReactNode;
  children: ReactNode;
  /** 아래 행동 영역. 창을 닫는 버튼 문구는 [닫기]로 통일한다. */
  footer?: ReactNode;
  className?: string;
}

export function Dialog({ open, onOpenChange, title, description, closeLabel, headerExtra, children, footer, className }: OverlayWindowProps) {
  const focus = useFocusReturn();
  return (
    <DialogPrimitive.Root open={open} onOpenChange={onOpenChange}>
      <DialogPrimitive.Portal>
        <DialogPrimitive.Overlay className={overlayScrimClass} />
        <DialogPrimitive.Content
          {...focus}
          className={cn(
            "fixed top-1/2 left-1/2 z-50 flex max-h-[85dvh] w-[min(560px,calc(100vw-32px))] -translate-x-1/2 -translate-y-1/2 flex-col rounded-lg bg-surface-overlay shadow-modal outline-none motion-dialog",
            className,
          )}
        >
          <OverlayHeader title={title} description={description} closeLabel={closeLabel} headerExtra={headerExtra} />
          <div className="min-h-0 flex-1 overflow-y-auto px-4 py-4 md:px-5">{children}</div>
          {footer && <div className="border-t border-border-subtle px-4 py-3 md:px-5">{footer}</div>}
        </DialogPrimitive.Content>
      </DialogPrimitive.Portal>
    </DialogPrimitive.Root>
  );
}

export interface SheetProps extends OverlayWindowProps {
  /** 모바일 바텀시트의 처음 높이. 긴 읽기(근거·대화)는 full, 훑어보기(노드 요약)는 half. */
  mobileSnap?: SheetSnap;
}

/** 데스크톱(>768px)은 오른쪽에서 나오는 패널, 모바일(≤768px)은 스냅되는 BottomSheet. */
export function Sheet({ mobileSnap = "full", ...props }: SheetProps) {
  const isMobile = useMediaQuery("(max-width: 768px)");
  if (isMobile) return <BottomSheet {...props} defaultSnap={mobileSnap} />;
  return <SideSheet {...props} />;
}

function SideSheet({ open, onOpenChange, title, description, closeLabel, headerExtra, children, footer, className }: OverlayWindowProps) {
  const focus = useFocusReturn();
  return (
    <DialogPrimitive.Root open={open} onOpenChange={onOpenChange}>
      <DialogPrimitive.Portal>
        <DialogPrimitive.Overlay className={overlayScrimClass} />
        <DialogPrimitive.Content
          {...focus}
          className={cn(
            "fixed inset-y-0 right-0 z-50 flex w-[min(480px,100vw)] flex-col bg-surface-overlay shadow-modal outline-none motion-sheet-right",
            className,
          )}
        >
          <OverlayHeader title={title} description={description} closeLabel={closeLabel} headerExtra={headerExtra} />
          <div className="min-h-0 flex-1 overflow-y-auto px-5 py-4">{children}</div>
          {footer && <div className="border-t border-border-subtle px-5 py-3">{footer}</div>}
        </DialogPrimitive.Content>
      </DialogPrimitive.Portal>
    </DialogPrimitive.Root>
  );
}
