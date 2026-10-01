import { cva, type VariantProps } from "class-variance-authority";
import type { ComponentProps } from "react";
import { cn } from "@/lib/utils";

// 순수 상태 표시 전용(누를 수 없음). 한 행에 최대 1~2개. 색만으로 뜻을 전하지 않도록 글자(필요하면 아이콘)를 넣는다.
// neutral: 기본 약한 중성 배지. warning·error: 확인이 필요한 상태만. 성공·정보 전용 색은 두지 않는다.
export const badgeVariants = cva(
  "inline-flex shrink-0 items-center gap-1 rounded-sm bg-surface-sunken px-2 py-1 text-sm leading-none font-medium whitespace-nowrap [&_svg]:size-3.5 [&_svg]:shrink-0",
  {
    variants: {
      variant: {
        neutral: "text-text-secondary",
        warning: "text-warning",
        error: "text-error",
      },
    },
    defaultVariants: { variant: "neutral" },
  },
);

export interface BadgeProps extends ComponentProps<"span">, VariantProps<typeof badgeVariants> {}

export function Badge({ className, variant, ...props }: BadgeProps) {
  return <span className={cn(badgeVariants({ variant }), className)} {...props} />;
}
