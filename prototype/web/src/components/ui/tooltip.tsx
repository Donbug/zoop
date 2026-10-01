import * as TooltipPrimitive from "@radix-ui/react-tooltip";
import type { ReactNode } from "react";

/** 앱 최상단에서 한 번 감싼다. 마우스를 올리거나 키보드로 포커스하면 200ms 뒤 나타난다. */
export function TooltipProvider({ children }: { children: ReactNode }) {
  return <TooltipPrimitive.Provider delayDuration={200}>{children}</TooltipPrimitive.Provider>;
}

interface TooltipProps {
  /** 한 줄 보조 설명. 터치 기기에서는 보이지 않으므로 꼭 필요한 정보는 Popover나 본문에 둔다. */
  content: ReactNode;
  /** 트리거는 포커스를 받을 수 있는 요소(button, a, tabIndex=0)여야 한다. */
  children: ReactNode;
  side?: "top" | "bottom" | "left" | "right";
}

export function Tooltip({ content, children, side = "top" }: TooltipProps) {
  return (
    <TooltipPrimitive.Root>
      <TooltipPrimitive.Trigger asChild>{children}</TooltipPrimitive.Trigger>
      <TooltipPrimitive.Portal>
        <TooltipPrimitive.Content
          side={side}
          sideOffset={6}
          collisionPadding={8}
          className="z-50 max-w-72 rounded-sm bg-text-primary px-3 py-2 text-sm leading-normal text-text-inverse shadow-overlay motion-pop"
        >
          {content}
          <TooltipPrimitive.Arrow className="fill-text-primary" />
        </TooltipPrimitive.Content>
      </TooltipPrimitive.Portal>
    </TooltipPrimitive.Root>
  );
}
