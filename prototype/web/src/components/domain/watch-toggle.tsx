// WatchToggle: 사이드바·기업 노드 패널에서 관심 종목 등록·해제(FS027).
//  - 누름 자체가 저장 요청이다(PUT /api/me/watchlist/{id} {watched}). 원하는 최종 상태를 보내므로 재전송해도 한 번만 반영된다.
//  - 저장에 성공한 뒤에만 눌림 상태가 바뀐다. 실패하면 이전 상태를 두고 알린 뒤 다시 누를 수 있다.
//  - 저장 뒤 개인화 그래프는 다시 조회만 한다. 그래프 조회가 실패해도 관심 저장을 다시 보내지 않는다(그래프 영역이 따로 재시도).
//  - 보유 종목은 관심에서 빼도 보유 노드로 남는다(보유는 가상 계좌가 정한다).
//  - 비회원·로그인 전에는 로그인 안내로 바뀐다. 상태는 aria-pressed + 채운 별 + 글자로 알린다(색만으로 구분하지 않는다).
import { LogIn, Star } from "lucide-react";
import { Link, useLocation } from "react-router";
import { useSession, useSetWatched, useSettings } from "@/api/queries";
import { Button } from "@/components/ui/button";
import { Tooltip } from "@/components/ui/tooltip";
import { useToast } from "@/components/ui/toast";
import { cn } from "@/lib/utils";

interface WatchToggleProps {
  companyId: string;
  companyName: string;
  /** button: 글자가 있는 버튼(기업 패널), icon: 44px 아이콘 버튼(목록 행 옆) */
  variant?: "button" | "icon";
  className?: string;
}

export function WatchToggle({ companyId, companyName, variant = "button", className }: WatchToggleProps) {
  const session = useSession();
  const location = useLocation();
  const member = session.data?.kind === "member";
  const settings = useSettings(member);
  const save = useSetWatched();
  const toast = useToast();

  if (!session.data) return null;
  if (!member) {
    const label = "로그인하고 관심 종목에 담기";
    const link = (
      <Link to="/login" state={{ from: location.pathname + location.search }} aria-label={variant === "icon" ? `${companyName}: ${label}` : undefined}>
        <LogIn aria-hidden="true" />
        {variant === "button" && label}
      </Link>
    );
    return variant === "icon" ? (
      <Tooltip content={label}>
        <Button asChild variant="ghost" size="icon" className={className}>
          {link}
        </Button>
      </Tooltip>
    ) : (
      <Button asChild variant="secondary" className={className}>
        {link}
      </Button>
    );
  }

  const watched = settings.data?.watchlistIds.includes(companyId) ?? false;
  const toggle = () =>
    save.mutate(
      { companyId, watched: !watched },
      {
        onError: () =>
          toast({
            title: watched ? "관심 종목에서 빼지 못했어요" : "관심 종목에 담지 못했어요",
            description: "관심 상태는 그대로예요. 잠시 뒤 다시 눌러 주세요.",
            tone: "warning",
          }),
      },
    );
  const label = watched ? "관심 종목" : "관심 종목에 담기";
  const common = {
    "aria-pressed": watched,
    disabled: settings.isPending,
    loading: save.isPending,
    onClick: toggle,
  };
  const icon = <Star className={cn(watched && "fill-current text-brand-primary")} aria-hidden="true" />;

  if (variant === "icon")
    return (
      <Tooltip content={watched ? "관심 종목에서 빼기" : "관심 종목에 담기"}>
        <Button {...common} variant="ghost" size="icon" aria-label={`${companyName} 관심 종목`} className={className}>
          {icon}
        </Button>
      </Tooltip>
    );
  return (
    <Button {...common} variant="secondary" aria-label={`${companyName} ${label}`} className={className}>
      {icon}
      {label}
    </Button>
  );
}
