import type { ComponentProps, ReactNode } from "react";
import { Link } from "react-router";
import { cn } from "@/lib/utils";

type Divider = "indented" | "full" | "none";

interface ListRowBase {
  /** 왼쪽 24px 영역: 아이콘·기업 마커·상태 도형. 장식이면 aria-hidden을 붙여 넘긴다. */
  leading?: ReactNode;
  /** 한 줄 제목(15px) */
  title: ReactNode;
  /** 보조 설명(13px, text-secondary) */
  description?: ReactNode;
  /** 오른쪽: 수치·배지 1개·화살표 */
  trailing?: ReactNode;
  /** 선택 상태: selected 배경 + 굵은 제목. 버튼이면 aria-pressed, 링크면 aria-current로 전달된다. */
  selected?: boolean;
  /** 아래 구분선. indented는 leading이 있으면 56px, 없으면 16px 들여쓴다. */
  divider?: Divider;
  className?: string;
}

/** 링크 행: 다른 화면으로 이동 */
type LinkRowProps = ListRowBase & { to: string } & Omit<ComponentProps<typeof Link>, "to" | "title" | "className" | "children">;
/** 버튼 행: 같은 화면에서 선택·열기 */
type ButtonRowProps = ListRowBase & { to?: undefined } & Omit<ComponentProps<"button">, "title" | "className" | "children">;

export type ListRowProps = LinkRowProps | ButtonRowProps;

/**
 * 카드 대신 쓰는 목록 행. 최소 높이 48px(누르는 영역 44px 이상). <li> 안에 넣어 쓴다.
 * - to가 있으면 링크, onClick이 있으면 버튼, 둘 다 없으면 누를 수 없는 정적 행.
 * - 행 안에 다른 버튼을 넣지 않는다(중첩 상호작용 금지). 행 옆 행동이 필요하면 trailing을 행 밖에 둔다.
 */
export function ListRow(props: ListRowProps) {
  const { leading, title, description, trailing, selected = false, divider = "indented", className } = props;
  const body = (
    <>
      {leading && (
        <span className="flex size-6 shrink-0 items-center justify-center text-text-secondary [&_svg]:size-5" aria-hidden="true">
          {leading}
        </span>
      )}
      <span className="flex min-w-0 flex-1 flex-col gap-0.5">
        <span className={cn("text-base leading-snug text-text-primary", selected ? "font-semibold" : "font-medium")}>{title}</span>
        {description && <span className="text-sm text-text-secondary">{description}</span>}
      </span>
      {trailing && <span className="flex shrink-0 items-center gap-2 text-sm text-text-secondary">{trailing}</span>}
    </>
  );

  const rowClass = cn(
    "relative flex min-h-12 w-full items-center gap-4 px-4 py-3 text-left",
    divider !== "none" && "after:absolute after:right-0 after:bottom-0 after:h-px after:bg-border-subtle after:content-['']",
    divider === "full" && "after:left-0",
    divider === "indented" && (leading ? "after:left-14" : "after:left-4"),
    selected && "bg-surface-selected",
    className,
  );
  const interactiveClass = cn(
    "transition-token focus-visible:-outline-offset-2",
    selected ? "hover:bg-surface-selected" : "hover:bg-surface-sunken active:bg-surface-selected",
  );

  if (props.to !== undefined) {
    const { leading: _l, title: _t, description: _d, trailing: _tr, selected: _s, divider: _dv, className: _c, to, ...rest } = props;
    return (
      <Link to={to} aria-current={selected ? "page" : undefined} className={cn(rowClass, interactiveClass)} {...rest}>
        {body}
      </Link>
    );
  }

  const { leading: _l, title: _t, description: _d, trailing: _tr, selected: _s, divider: _dv, className: _c, to: _to, ...rest } = props;
  if (rest.onClick) {
    return (
      <button
        type="button"
        aria-pressed={selected}
        className={cn(rowClass, interactiveClass, "disabled:cursor-not-allowed disabled:hover:bg-transparent disabled:[&_span]:text-text-tertiary")}
        {...rest}
      >
        {body}
      </button>
    );
  }
  return <div className={rowClass}>{body}</div>;
}
