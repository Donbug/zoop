import * as ToggleGroup from "@radix-ui/react-toggle-group";
import { useLayoutEffect, useRef, useState, type ReactNode } from "react";
import { cn } from "@/lib/utils";
import { Tooltip } from "./tooltip";

export interface SegmentedOption<T extends string> {
  value: T;
  label: ReactNode;
  /** 스크린리더 이름을 label과 다르게 주고 싶을 때 */
  ariaLabel?: string;
  disabled?: boolean;
  /** disabled일 때 이유. 포커스·호버하면 툴팁으로 보인다. */
  disabledReason?: string;
}

interface SegmentedProps<T extends string> {
  value: T;
  onValueChange: (value: T) => void;
  options: SegmentedOption<T>[];
  /** 그룹 이름(필수, 예: "탐색 모드") */
  "aria-label": string;
  /** true면 부모 폭을 똑같이 나눈다(모바일 기본). */
  fill?: boolean;
  className?: string;
  /** 이미 고른 항목을 다시 눌렀을 때(선택은 그대로). 예: 진행 중인 모드 전환을 거두기 */
  onReselect?: (value: T) => void;
}

/**
 * 2~4개 중 하나를 고르는 전환 컨트롤(모드·보기). 선택 해제는 할 수 없다. 좌우 방향키로 이동한다.
 * 48px 트랙(항목 40px), 선택 항목은 들린 표면 + 굵은 글자(색만으로 구분하지 않음).
 * 들린 표면(thumb)은 하나만 두고 선택한 항목 자리로 미끄러뜨린다(SEED standard 곡선, 200ms).
 */
export function Segmented<T extends string>({ value, onValueChange, options, fill, className, onReselect, ...rest }: SegmentedProps<T>) {
  const rootRef = useRef<HTMLDivElement>(null);
  const [thumb, setThumb] = useState<{ x: number; width: number; animate: boolean } | null>(null);

  // 선택 항목의 위치를 재서 thumb를 옮긴다. 트랙 폭이 바뀌면(화면 회전·글꼴 로드) 애니메이션 없이 다시 맞춘다.
  useLayoutEffect(() => {
    const root = rootRef.current;
    if (!root) return;
    const measure = (animate: boolean) => {
      const active = root.querySelector<HTMLElement>('[data-state="on"]');
      if (!active) {
        setThumb(null);
        return;
      }
      const rootBox = root.getBoundingClientRect();
      const box = active.getBoundingClientRect();
      setThumb((prev) => ({ x: box.left - rootBox.left, width: box.width, animate: animate && prev !== null }));
    };
    measure(true);
    const observer = new ResizeObserver(() => measure(false));
    observer.observe(root);
    return () => observer.disconnect();
  }, [value, options.length]);

  return (
    <ToggleGroup.Root
      ref={rootRef}
      type="single"
      value={value}
      // 고른 항목을 다시 누르면 Radix는 빈 값(선택 해제)을 준다. 선택은 바꾸지 않고 다시 눌렀다고만 알린다.
      onValueChange={(next) => (next ? onValueChange(next as T) : onReselect?.(value))}
      aria-label={rest["aria-label"]}
      className={cn("relative inline-flex h-12 max-w-full min-w-0 items-stretch gap-1 rounded-sm bg-surface-sunken p-1", fill && "flex w-full", className)}
    >
      {thumb && (
        <span
          aria-hidden="true"
          data-segmented-thumb=""
          className={cn(
            "absolute top-1 bottom-1 left-0 rounded-sm bg-surface-raised shadow-raised",
            // 위치만 미끄러뜨리고 폭은 바로 맞춘다. 배율을 쓰면 모서리·그림자가 일그러지고, width 전환은 레이아웃을 다시 계산한다.
            thumb.animate && "transition-[translate] duration-(--zoop-motion-duration-d4) ease-standard",
          )}
          style={{ translate: `${thumb.x}px 0`, width: thumb.width }}
        />
      )}
      {options.map((option) => {
        const item = (
          <ToggleGroup.Item
            key={option.value}
            value={option.value}
            disabled={option.disabled}
            aria-label={option.disabledReason ? `${option.ariaLabel ?? String(option.label)} (${option.disabledReason})` : option.ariaLabel}
            className={cn(
              "pressable relative inline-flex min-w-0 items-center justify-center gap-1.5 rounded-sm px-3 text-sm font-medium whitespace-nowrap text-text-secondary hover:text-text-primary [&_svg]:size-4 [&_svg]:shrink-0",
              "disabled:cursor-not-allowed disabled:text-text-tertiary disabled:hover:text-text-tertiary",
              "data-[state=on]:font-semibold data-[state=on]:text-text-primary",
              // 첫 측정 전에는 항목 자체가 들린 표면을 그린다.
              !thumb && "data-[state=on]:bg-surface-raised data-[state=on]:shadow-raised",
              fill && "flex-1",
            )}
          >
            {option.label}
          </ToggleGroup.Item>
        );
        return option.disabled && option.disabledReason ? (
          <Tooltip key={option.value} content={option.disabledReason}>
            <span tabIndex={0} className={cn("flex rounded-sm", fill && "flex-1 [&>*]:flex-1")}>
              {item}
            </span>
          </Tooltip>
        ) : (
          item
        );
      })}
    </ToggleGroup.Root>
  );
}
