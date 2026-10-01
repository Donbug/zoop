import * as PopoverPrimitive from "@radix-ui/react-popover";
import type { ReactNode } from "react";
import { cn } from "@/lib/utils";

interface PopoverProps {
  /** 여는 버튼. 포커스를 받을 수 있는 요소 하나(asChild로 감싼다). */
  trigger: ReactNode;
  children: ReactNode;
  /** 팝오버 안 내용의 접근 가능한 이름 */
  label: string;
  side?: "top" | "bottom" | "left" | "right";
  align?: "start" | "center" | "end";
  className?: string;
  /** 제어 모드(예: 목록에서 고르면 닫기). 없으면 스스로 열고 닫는다. */
  open?: boolean;
  onOpenChange?: (open: boolean) => void;
}

/** 눌러서 여는 짧은 설명·설정. 터치에서도 동작한다(Tooltip은 호버 전용). Esc·바깥 누르기로 닫힌다. */
export function Popover({ trigger, children, label, side = "bottom", align = "end", className, open, onOpenChange }: PopoverProps) {
  return (
    <PopoverPrimitive.Root open={open} onOpenChange={onOpenChange}>
      <PopoverPrimitive.Trigger asChild>{trigger}</PopoverPrimitive.Trigger>
      <PopoverPrimitive.Portal>
        <PopoverPrimitive.Content
          side={side}
          align={align}
          sideOffset={6}
          collisionPadding={12}
          aria-label={label}
          className={cn(
            "z-50 flex w-[min(320px,calc(100vw-24px))] flex-col gap-2 rounded-lg bg-surface-overlay p-4 text-sm text-text-secondary shadow-overlay motion-pop",
            className,
          )}
        >
          {children}
        </PopoverPrimitive.Content>
      </PopoverPrimitive.Portal>
    </PopoverPrimitive.Root>
  );
}
