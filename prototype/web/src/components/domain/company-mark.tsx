// CompanyMark: 목록·머리글에서 기업을 지도 노드와 같은 모양(상징색 원 + 로고, 없으면 이니셜)으로 표시한다.
// 로고는 CSS mask로 한 가지 색(흰색/거의 검정 중 대비가 큰 쪽)으로 칠한다. 장식이므로 스크린리더에는 숨긴다.
import { companyFillVar, contrastRatio, glyphColor, initials } from "@/lib/graph-visuals";
import { cn } from "@/lib/utils";

interface CompanyMarkProps {
  id: string;
  name: string;
  brandColor?: string | null;
  logoUrl?: string | null;
  /** 지름(px). 목록 행 24, 머리글 40 */
  size?: number;
  className?: string;
}

export function CompanyMark({ id, name, brandColor, logoUrl, size = 24, className }: CompanyMarkProps) {
  const fill = companyFillVar(id, brandColor);
  // 폴백 팔레트는 모두 흰 글리프와 4.5:1 이상이 되도록 골랐다.
  const glyph = brandColor ? glyphColor(brandColor) : "#FFFFFF";
  const needsRing = brandColor ? contrastRatio(brandColor, "#FFFFFF") < 1.3 || contrastRatio(brandColor, "#0E1110") < 1.3 : false;
  const text = initials(name);
  return (
    <span
      aria-hidden="true"
      className={cn("inline-flex shrink-0 items-center justify-center rounded-full font-bold", needsRing && "ring-1 ring-border-control", className)}
      style={{ width: size, height: size, backgroundColor: fill, color: glyph, fontSize: Math.round(size * (text.length > 1 ? 0.36 : 0.44)) }}
    >
      {logoUrl ? (
        <span
          className="block"
          style={{
            width: size * 0.58,
            height: size * 0.58,
            backgroundColor: glyph,
            mask: `url("${logoUrl}") center / contain no-repeat`,
            WebkitMask: `url("${logoUrl}") center / contain no-repeat`,
          }}
        />
      ) : (
        <span className="leading-none">{text}</span>
      )}
    </span>
  );
}
