// Dialog·Sheet·BottomSheet가 함께 쓰는 머리글·딤·포커스 복귀. 화면에서 직접 쓰지 않는다.
import * as DialogPrimitive from "@radix-ui/react-dialog";
import { X } from "lucide-react";
import { useRef, type ReactNode } from "react";
import { cn } from "@/lib/utils";

export const overlayScrimClass = "fixed inset-0 z-40 bg-[rgb(0_0_0/0.4)] dark:bg-[rgb(0_0_0/0.6)] motion-scrim";

/** 열기 직전에 포커스가 있던 요소로 닫힌 뒤 포커스를 되돌린다(NFR-12). */
export function useFocusReturn() {
  const lastFocused = useRef<HTMLElement | null>(null);
  return {
    onOpenAutoFocus: () => {
      lastFocused.current = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    },
    onCloseAutoFocus: (event: Event) => {
      const target = lastFocused.current;
      if (target && target.isConnected) {
        event.preventDefault();
        target.focus();
      }
    },
  };
}

interface OverlayHeaderProps {
  title: ReactNode;
  description?: ReactNode;
  closeLabel?: string;
  headerExtra?: ReactNode;
  className?: string;
}

export function OverlayHeader({ title, description, closeLabel, headerExtra, className }: OverlayHeaderProps) {
  return (
    <div className={cn("flex items-start gap-3 border-b border-border-subtle py-3 pr-2 pl-4 md:pl-5", className)}>
      <div className="flex min-w-0 flex-1 flex-col gap-1 pt-2">
        <DialogPrimitive.Title className="text-xl leading-tight font-semibold text-text-primary">{title}</DialogPrimitive.Title>
        {description ? (
          <DialogPrimitive.Description className="text-sm text-text-secondary">{description}</DialogPrimitive.Description>
        ) : (
          <DialogPrimitive.Description className="sr-only">{closeLabel ?? "창"}</DialogPrimitive.Description>
        )}
        {headerExtra}
      </div>
      <DialogPrimitive.Close
        aria-label={closeLabel ?? "닫기"}
        className="relative z-10 flex size-11 shrink-0 items-center justify-center rounded-sm text-text-secondary transition-token hover:bg-surface-sunken hover:text-text-primary"
      >
        <X className="size-5" aria-hidden="true" />
      </DialogPrimitive.Close>
    </div>
  );
}
