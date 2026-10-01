// CompanyHeader: 상징색 표지 + 종목명 + 업종·티커 + 보유/관심 표지. 시세가 없으면 시세 자리를 그리지 않는다.
import { Star, Wallet } from "lucide-react";
import type { ReactNode } from "react";
import { Badge } from "@/components/ui/badge";
import { cn } from "@/lib/utils";
import { CompanyMark } from "./company-mark";

interface CompanyHeaderProps {
  id: string;
  name: string;
  ticker: string | null;
  sector?: string | null;
  brandColor?: string | null;
  logoUrl?: string | null;
  holding?: boolean | null;
  watch?: boolean | null;
  /** 비중은 서버가 원가 기준으로 준 값만 넣는다(없으면 비워 둔다). */
  holdingWeight?: number | null;
  as?: "h1" | "h2" | "h3" | "h4";
  headingRef?: React.Ref<HTMLHeadingElement>;
  actions?: ReactNode;
  className?: string;
}

export function CompanyHeader({
  id,
  name,
  ticker,
  sector,
  brandColor,
  logoUrl,
  holding,
  watch,
  holdingWeight,
  as: Heading = "h2",
  headingRef,
  actions,
  className,
}: CompanyHeaderProps) {
  const meta = [sector, ticker].filter(Boolean).join(" · ");
  const large = Heading === "h1";
  return (
    <div className={cn("flex items-center gap-3", className)}>
      <CompanyMark id={id} name={name} brandColor={brandColor} logoUrl={logoUrl} size={large ? 48 : 40} />
      <div className="flex min-w-0 flex-1 flex-col gap-1">
        <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
          <Heading ref={headingRef} tabIndex={-1} className={cn("leading-tight font-bold text-text-primary", large ? "text-2xl" : "text-xl")}>
            {name}
          </Heading>
          {actions && <div className="ml-auto flex items-center gap-2">{actions}</div>}
        </div>
        {(meta || holding || watch) && (
          <div className="flex flex-wrap items-center gap-x-2 gap-y-1 text-sm text-text-secondary">
            {meta && <span className="tabular-nums">{meta}</span>}
            {holding && (
              <Badge>
                <Wallet aria-hidden="true" />
                보유
                {holdingWeight != null && <span className="tabular-nums">· 원가 비중 {Math.round(holdingWeight * 100)}%</span>}
              </Badge>
            )}
            {watch && (
              <Badge>
                <Star aria-hidden="true" />
                관심
              </Badge>
            )}
          </div>
        )}
      </div>
    </div>
  );
}
