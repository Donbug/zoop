// 관리자 화면 전용 부품. 사용자 앱과 같은 토큰·글꼴·ui 컴포넌트 위에, 밀도 높은 운영 표와 상태 표기만 더한다.
// 상태는 색만으로 구분하지 않는다: 항상 아이콘 + 글자. 숫자는 tabular-nums(표 안은 전역 규칙으로 적용).
import type { LucideIcon } from "lucide-react";
import { useEffect, useRef, useState, type ComponentProps, type ReactNode } from "react";
import { cn } from "@/lib/utils";
import { formatKst } from "./format";

export type StatusTone = "neutral" | "success" | "progress" | "warning" | "error";

const toneClass: Record<StatusTone, string> = {
  neutral: "text-text-secondary",
  success: "text-brand-primary",
  progress: "text-text-primary",
  warning: "text-warning",
  error: "text-error",
};

/** 상태 표기: 아이콘 + 라벨. 아이콘 색이 톤을 보태지만 뜻은 글자가 전한다. */
export function StatusLabel({ icon: Icon, label, tone = "neutral", spin, className }: { icon: LucideIcon; label: string; tone?: StatusTone; spin?: boolean; className?: string }) {
  return (
    <span className={cn("inline-flex items-center gap-1.5 text-sm font-medium whitespace-nowrap text-text-primary", className)}>
      <Icon className={cn("size-4 shrink-0", toneClass[tone], spin && "animate-spin motion-reduce:animate-none")} aria-hidden="true" />
      {label}
    </span>
  );
}

/** KST 시각. 값이 없으면 대시. */
export function KstTime({ value, seconds, className }: { value: string | null | undefined; seconds?: boolean; className?: string }) {
  const text = formatKst(value, { seconds });
  if (!text) return <span className={cn("text-text-tertiary", className)}>–</span>;
  return (
    <time dateTime={value ?? undefined} className={cn("tabular-nums whitespace-nowrap", className)} title={`${text} KST`}>
      {text}
    </time>
  );
}

/** 운영 표. 행은 구분선만(카드 없음). 좁은 화면에서 가로로 넘치면 키보드로도 스크롤할 수 있게 초점을 받는다. */
export function DataTable({ caption, className, children }: { caption: string; className?: string; children: ReactNode }) {
  const ref = useRef<HTMLDivElement>(null);
  const [overflowing, setOverflowing] = useState(false);
  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    const observer = new ResizeObserver(() => setOverflowing(el.scrollWidth > el.clientWidth));
    observer.observe(el);
    if (el.firstElementChild) observer.observe(el.firstElementChild);
    return () => observer.disconnect();
  }, []);
  return (
    <div
      ref={ref}
      className={cn("min-w-0 overflow-x-auto focus-visible:outline-2 focus-visible:-outline-offset-2", className)}
      {...(overflowing ? { tabIndex: 0, role: "region", "aria-label": caption } : {})}
    >
      <table className="w-full border-collapse text-left text-base">
        <caption className="sr-only">{caption}</caption>
        {children}
      </table>
    </div>
  );
}

export function Th({ className, ...props }: ComponentProps<"th">) {
  return (
    <th
      scope="col"
      className={cn("sticky top-0 z-[1] h-10 border-b border-border-strong bg-surface-base px-3 text-sm font-semibold whitespace-nowrap text-text-secondary", className)}
      {...props}
    />
  );
}

export function Td({ className, ...props }: ComponentProps<"td">) {
  return <td className={cn("h-11 border-b border-border-subtle px-3 py-2 align-middle text-text-primary", className)} {...props} />;
}

/** 선택할 수 있는 표 행. 선택은 행 안의 버튼(첫 칸)이 담당하고, 행 전체를 눌러도 같은 동작을 한다. */
export function SelectableRow({ selected, onSelect, className, children }: { selected: boolean; onSelect: () => void; className?: string; children: ReactNode }) {
  return (
    <tr
      aria-selected={selected}
      onClick={(event) => {
        if ((event.target as HTMLElement).closest("button, a")) return;
        onSelect();
      }}
      className={cn("cursor-pointer transition-token hover:bg-surface-sunken", selected && "bg-surface-selected hover:bg-surface-selected", className)}
    >
      {children}
    </tr>
  );
}

/** 대시보드·요약 수치 한 칸. 상자 없이 라벨 + 큰 숫자 + 보조 줄. */
export function Metric({ label, value, detail, icon: Icon }: { label: string; value: ReactNode; detail?: ReactNode; icon?: LucideIcon }) {
  return (
    <div className="flex min-w-0 flex-col gap-1 py-1">
      <dt className="flex items-center gap-1.5 text-sm font-medium text-text-secondary">
        {Icon && <Icon className="size-4 shrink-0" aria-hidden="true" />}
        {label}
      </dt>
      <dd className="text-xl font-bold text-text-primary tabular-nums">{value}</dd>
      {detail && <dd className="text-sm text-text-secondary">{detail}</dd>}
    </div>
  );
}

/** 관리자 화면 제목 줄: 제목(화면당 1회) + 오른쪽 행동. */
export function AdminPageHeader({ title, icon: Icon, actions }: { title: string; icon: LucideIcon; actions?: ReactNode }) {
  return (
    <div className="flex min-h-14 flex-wrap items-center gap-3">
      <h1 className="flex flex-1 items-center gap-2 text-xl font-bold text-text-primary">
        <Icon className="size-6 text-text-secondary" aria-hidden="true" />
        {title}
      </h1>
      {actions && <div className="flex flex-wrap items-center gap-2">{actions}</div>}
    </div>
  );
}

/** 관리자 화면의 구획: 제목 + 내용. 상자를 씌우지 않고 위 구분선으로 나눈다. */
export function AdminSection({ title, icon: Icon, actions, id, className, children }: { title: string; icon?: LucideIcon; actions?: ReactNode; id?: string; className?: string; children: ReactNode }) {
  const headingId = id ?? undefined;
  return (
    <section aria-labelledby={headingId} className={cn("flex min-w-0 flex-col gap-2 border-t border-border-subtle pt-4", className)}>
      <div className="flex min-h-11 items-center gap-2">
        <h2 id={headingId} className="flex flex-1 items-center gap-2 text-lg font-semibold text-text-primary">
          {Icon && <Icon className="size-5 shrink-0 text-text-secondary" aria-hidden="true" />}
          {title}
        </h2>
        {actions}
      </div>
      {children}
    </section>
  );
}
