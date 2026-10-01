import { Search, X } from "lucide-react";
import { useId, type ComponentProps } from "react";
import { cn } from "@/lib/utils";

// 44px 높이. 모바일은 16px 글자(iOS 포커스 확대 방지), 데스크톱은 15px.
const fieldBase =
  "h-11 w-full rounded-sm border border-border-control bg-surface-raised px-3 text-md text-text-primary placeholder:text-text-tertiary transition-token hover:border-text-secondary focus-visible:border-border-focus disabled:cursor-not-allowed disabled:border-border-subtle disabled:bg-surface-sunken disabled:text-text-tertiary aria-invalid:border-error md:text-base";

export interface InputProps extends ComponentProps<"input"> {
  /** 화면에 보이는 라벨. 숨기고 싶으면 hideLabel. 라벨은 항상 필요하다(접근성). */
  label: string;
  hideLabel?: boolean;
  /** 오류 문구. 있으면 aria-invalid와 aria-describedby가 자동으로 연결된다. */
  error?: string;
  hint?: string;
  /** search: 돋보기 아이콘 + 지우기 버튼 */
  variant?: "default" | "search";
  /** search 변형에서 입력값 지우기 버튼을 눌렀을 때 */
  onClear?: () => void;
}

export function Input({ label, hideLabel, error, hint, variant = "default", onClear, className, id, ...props }: InputProps) {
  const autoId = useId();
  const inputId = id ?? autoId;
  const errorId = `${inputId}-error`;
  const hintId = `${inputId}-hint`;
  const describedBy = [error ? errorId : null, hint ? hintId : null].filter(Boolean).join(" ") || undefined;
  const hasValue = typeof props.value === "string" && props.value.length > 0;

  return (
    <div className={cn("flex flex-col gap-1.5", className)}>
      <label htmlFor={inputId} className={cn("text-sm font-medium text-text-primary", hideLabel && "sr-only")}>
        {label}
      </label>
      <div className="relative">
        {variant === "search" && (
          <Search className="pointer-events-none absolute top-1/2 left-3 size-4 -translate-y-1/2 text-text-tertiary" aria-hidden="true" />
        )}
        <input
          id={inputId}
          type={variant === "search" ? "search" : props.type}
          aria-invalid={error ? true : undefined}
          aria-describedby={describedBy}
          className={cn(fieldBase, variant === "search" && "pr-11 pl-9 [&::-webkit-search-cancel-button]:hidden")}
          {...props}
        />
        {variant === "search" && hasValue && onClear && (
          <button
            type="button"
            onClick={onClear}
            aria-label="검색어 지우기"
            className="absolute top-0 right-0 flex size-11 items-center justify-center rounded-sm text-text-secondary hover:text-text-primary"
          >
            <X className="size-4" aria-hidden="true" />
          </button>
        )}
      </div>
      {hint && !error && (
        <p id={hintId} className="text-sm text-text-secondary">
          {hint}
        </p>
      )}
      {error && (
        <p id={errorId} className="text-sm font-medium text-error">
          {error}
        </p>
      )}
    </div>
  );
}
