import { Slot } from "@radix-ui/react-slot";
import { cva, type VariantProps } from "class-variance-authority";
import { Loader2 } from "lucide-react";
import type { ComponentProps } from "react";
import { cn } from "@/lib/utils";

/**
 * 보이는 크기가 44px보다 작아도 누를 수 있는 영역은 최소 44×44px로 넓힌다(투명 ::after).
 * 인접 컨트롤과 겹치지 않도록 버튼 사이 간격은 호출부에서 확보한다.
 */
export const hitArea =
  "relative after:absolute after:top-1/2 after:left-1/2 after:h-[max(100%,44px)] after:w-[max(100%,44px)] after:-translate-x-1/2 after:-translate-y-1/2 after:content-['']";

// primary: 화면의 주 행동 1개에만. secondary: 그 밖의 행동. ghost: 도구 막대·목록 안의 가벼운 행동. link: 문장 안 행동.
// 비활성은 투명도 대신 전용 색으로 보여 글자 대비를 유지한다(text-tertiary 4.9:1).
export const buttonVariants = cva(
  cn(
    "inline-flex items-center justify-center gap-2 rounded-sm font-medium whitespace-nowrap pressable select-none [&.w-full]:[--press-scale:0.977]",
    "disabled:cursor-not-allowed aria-busy:cursor-progress [&_svg]:size-4 [&_svg]:shrink-0",
    hitArea,
  ),
  {
    variants: {
      variant: {
        primary:
          "bg-brand-primary text-brand-primary-foreground hover:bg-brand-primary-hover active:bg-brand-primary-active disabled:bg-surface-sunken disabled:text-text-tertiary",
        secondary:
          "border border-border-strong bg-surface-raised text-text-primary hover:bg-surface-sunken active:bg-surface-selected disabled:border-border-subtle disabled:bg-surface-sunken disabled:text-text-tertiary",
        ghost:
          "bg-transparent text-text-primary hover:bg-surface-sunken active:bg-surface-selected disabled:bg-transparent disabled:text-text-tertiary",
        link: "text-brand-primary underline-offset-4 hover:underline disabled:text-text-tertiary disabled:no-underline",
      },
      size: {
        /** 보이는 높이 36px, 누르는 영역 44px */
        sm: "h-9 px-3 text-sm",
        /** 44px */
        md: "h-11 px-4 text-base",
        /** 48px — 모바일 하단 주 행동 */
        lg: "h-12 px-5 text-md",
        /** 44×44 아이콘 버튼. aria-label 필수. */
        icon: "size-11 [&_svg]:size-5",
      },
    },
    compoundVariants: [{ variant: "link", className: "h-auto px-0" }],
    defaultVariants: { variant: "primary", size: "md" },
  },
);

export interface ButtonProps extends ComponentProps<"button">, VariantProps<typeof buttonVariants> {
  /** true면 자식 요소(예: 링크)에 버튼 스타일만 입힌다. */
  asChild?: boolean;
  /** 요청 중이면 스피너를 보여주고 클릭을 막는다. */
  loading?: boolean;
}

export function Button({ className, variant, size, asChild = false, loading = false, disabled, children, ...props }: ButtonProps) {
  const Comp = asChild ? Slot : "button";
  return (
    <Comp
      className={cn(buttonVariants({ variant, size }), className)}
      disabled={asChild ? undefined : disabled || loading}
      aria-busy={loading || undefined}
      {...props}
    >
      {asChild ? (
        children
      ) : (
        <>
          {loading && <Loader2 className="animate-spin" aria-hidden="true" />}
          {children}
        </>
      )}
    </Comp>
  );
}
