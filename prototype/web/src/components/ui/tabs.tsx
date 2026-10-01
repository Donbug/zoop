import * as TabsPrimitive from "@radix-ui/react-tabs";
import { useLayoutEffect, useRef, useState, type ComponentProps } from "react";
import { cn } from "@/lib/utils";

/**
 * 같은 대상의 내용 영역을 바꾸는 탭(예: 핵심 요약 / 관계도). 좌우 방향키로 이동한다.
 * 탭은 영역을 똑같이 나눠 가로 스크롤이 생기지 않는다(최대 4개). 모드·보기 전환처럼 내용 영역이 없는 선택은 Segmented를 쓴다.
 * 현재 탭 밑줄(2px)은 하나만 두고 고른 탭으로 미끄러진다(SEED standard 곡선, 250ms).
 */
export const Tabs = TabsPrimitive.Root;

export function TabsList({ className, children, ...props }: ComponentProps<typeof TabsPrimitive.List>) {
  const ref = useRef<HTMLDivElement>(null);
  const [bar, setBar] = useState<{ x: number; width: number; animate: boolean } | null>(null);

  useLayoutEffect(() => {
    const list = ref.current;
    if (!list) return;
    const measure = (animate: boolean) => {
      const active = list.querySelector<HTMLElement>('[role="tab"][data-state="active"]');
      if (!active) return;
      const listBox = list.getBoundingClientRect();
      const box = active.getBoundingClientRect();
      setBar((prev) => ({ x: box.left - listBox.left, width: box.width, animate: animate && prev !== null }));
    };
    measure(false);
    // 선택은 Radix가 data-state로 바꾸므로(비제어 탭 포함) 속성 변화를 지켜본다.
    const mutations = new MutationObserver(() => measure(true));
    mutations.observe(list, { subtree: true, attributes: true, attributeFilter: ["data-state"] });
    const resize = new ResizeObserver(() => measure(false));
    resize.observe(list);
    return () => {
      mutations.disconnect();
      resize.disconnect();
    };
  }, []);

  return (
    <TabsPrimitive.List ref={ref} className={cn("relative flex w-full min-w-0 items-stretch border-b border-border-subtle", className)} {...props}>
      {children}
      {bar && (
        <span
          aria-hidden="true"
          className={cn(
            "pointer-events-none absolute bottom-0 left-0 h-0.5 w-px origin-left bg-brand-primary",
            // 폭 1px 막대를 가로 배율로 늘린다(width 전환은 레이아웃을 다시 계산하므로 쓰지 않는다).
            bar.animate && "transition-[translate,scale] duration-(--zoop-motion-duration-normal) ease-standard",
          )}
          style={{ translate: `${bar.x}px 0`, scale: `${bar.width} 1` }}
        />
      )}
    </TabsPrimitive.List>
  );
}

export function TabsTrigger({ className, ...props }: ComponentProps<typeof TabsPrimitive.Trigger>) {
  return (
    <TabsPrimitive.Trigger
      className={cn(
        "inline-flex h-11 min-w-0 flex-1 items-center justify-center gap-1.5 px-3 text-base font-medium text-text-secondary transition-token hover:text-text-primary disabled:cursor-not-allowed disabled:text-text-tertiary [&_svg]:size-4 [&_svg]:shrink-0",
        "data-[state=active]:font-semibold data-[state=active]:text-text-primary",
        "focus-visible:-outline-offset-2",
        className,
      )}
      {...props}
    />
  );
}

export function TabsContent({ className, ...props }: ComponentProps<typeof TabsPrimitive.Content>) {
  return <TabsPrimitive.Content className={cn("focus-visible:outline-offset-4 data-[state=active]:animate-[zoop-fade-in_var(--zoop-motion-duration-normal)_var(--ease-enter)]", className)} {...props} />;
}
