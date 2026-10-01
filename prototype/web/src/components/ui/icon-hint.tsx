// IconHint: 글자 대신 아이콘 하나로 보조 정보를 보여준다. 설명문·부제·메타 라벨을 화면에 늘어놓지 않기 위한 부품.
// - 마우스를 올리거나 키보드로 포커스하면 툴팁(label 한 줄)
// - 누르면(터치 포함) 팝오버로 label + children(짧은 설명)
// - 스크린리더 이름은 label. 보이는 크기는 28px, 누르는 영역은 44px.
import * as PopoverPrimitive from "@radix-ui/react-popover";
import * as TooltipPrimitive from "@radix-ui/react-tooltip";
import type { LucideIcon } from "lucide-react";
import type { ReactNode } from "react";
import { cn } from "@/lib/utils";
import { hitArea } from "./button";

interface IconHintProps {
  icon: LucideIcon;
  /** 툴팁·스크린리더 이름(한 줄) */
  label: string;
  /** 눌렀을 때 label 아래에 덧붙일 설명. 없으면 label만 보인다. */
  children?: ReactNode;
  /** 아이콘 색 */
  tone?: "neutral" | "warning" | "error" | "brand";
  /** 보이는 크기: sm 28px(문장 옆), md 44px(도구 막대) */
  size?: "sm" | "md";
  className?: string;
}

const toneClass = {
  neutral: "text-text-secondary hover:text-text-primary",
  warning: "text-warning",
  error: "text-error",
  brand: "text-brand-primary",
};

export function IconHint({ icon: Icon, label, children, tone = "neutral", size = "sm", className }: IconHintProps) {
  return (
    <PopoverPrimitive.Root>
      <TooltipPrimitive.Root>
        <TooltipPrimitive.Trigger asChild>
          <PopoverPrimitive.Trigger
            aria-label={label}
            className={cn(
              "pressable inline-flex shrink-0 items-center justify-center rounded-sm hover:bg-surface-sunken",
              size === "sm" ? cn("size-7 [&_svg]:size-4", hitArea) : "size-11 [&_svg]:size-5",
              toneClass[tone],
              className,
            )}
          >
            <Icon aria-hidden="true" />
          </PopoverPrimitive.Trigger>
        </TooltipPrimitive.Trigger>
        <TooltipPrimitive.Portal>
          <TooltipPrimitive.Content
            side="top"
            sideOffset={6}
            collisionPadding={8}
            className="z-50 max-w-72 rounded-sm bg-text-primary px-3 py-2 text-sm leading-normal text-text-inverse shadow-overlay motion-pop"
          >
            {label}
            <TooltipPrimitive.Arrow className="fill-text-primary" />
          </TooltipPrimitive.Content>
        </TooltipPrimitive.Portal>
      </TooltipPrimitive.Root>
      <PopoverPrimitive.Portal>
        <PopoverPrimitive.Content
          side="bottom"
          align="start"
          sideOffset={6}
          collisionPadding={12}
          aria-label={label}
          className="z-50 flex w-[min(320px,calc(100vw-24px))] flex-col gap-1 rounded-lg bg-surface-overlay p-4 text-sm text-text-secondary shadow-overlay motion-pop"
        >
          <p className="font-semibold text-text-primary">{label}</p>
          {children}
        </PopoverPrimitive.Content>
      </PopoverPrimitive.Portal>
    </PopoverPrimitive.Root>
  );
}
