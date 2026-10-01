import * as ToastPrimitive from "@radix-ui/react-toast";
import { CircleCheck, TriangleAlert, X } from "lucide-react";
import { createContext, useCallback, useContext, useMemo, useState, type ReactNode } from "react";

// 짧은 결과 알림(한 문장). 3초(경고는 5초) 뒤 사라지고, 마우스를 올리거나 포커스하면 멈춘다.
// 모바일은 하단 탭바 위에 뜬다. 되돌릴 수 없는 오류·긴 설명은 토스트 대신 ErrorState를 쓴다.

type ToastTone = "neutral" | "success" | "warning";
interface ToastItem {
  id: number;
  title: string;
  description?: string;
  tone: ToastTone;
  /** 닫혀도 퇴장 모션이 끝날 때까지 남겨 두고, 다음 알림을 띄울 때 정리한다. */
  open: boolean;
}

type ShowToast = (toast: Omit<ToastItem, "id" | "tone" | "open"> & { tone?: ToastTone }) => void;
const ToastContext = createContext<ShowToast | null>(null);

const toneIcon = {
  neutral: null,
  success: <CircleCheck className="mt-0.5 size-5 shrink-0 text-brand-primary" aria-hidden="true" />,
  warning: <TriangleAlert className="mt-0.5 size-5 shrink-0 text-warning" aria-hidden="true" />,
} satisfies Record<ToastTone, ReactNode>;

export function ToastProvider({ children }: { children: ReactNode }) {
  const [items, setItems] = useState<ToastItem[]>([]);
  const show = useCallback<ShowToast>((toast) => {
    setItems((prev) => [...prev.filter((t) => t.open), { id: Date.now() + Math.random(), tone: "neutral", open: true, ...toast }]);
  }, []);
  const value = useMemo(() => show, [show]);

  return (
    <ToastContext.Provider value={value}>
      <ToastPrimitive.Provider duration={3000} label="알림">
        {children}
        {items.map((item) => (
          <ToastPrimitive.Root
            key={item.id}
            type="foreground"
            open={item.open}
            duration={item.tone === "warning" ? 5000 : undefined}
            onOpenChange={(open) => {
              if (!open) setItems((prev) => prev.map((t) => (t.id === item.id ? { ...t, open: false } : t)));
            }}
            className="flex items-start gap-3 rounded-lg bg-surface-overlay py-3 pr-1 pl-4 shadow-overlay motion-toast"
          >
            {toneIcon[item.tone]}
            <div className="flex min-w-0 flex-1 flex-col gap-0.5 pt-0.5">
              <ToastPrimitive.Title className="text-base font-semibold text-text-primary">{item.title}</ToastPrimitive.Title>
              {item.description && (
                <ToastPrimitive.Description className="text-sm text-text-secondary">{item.description}</ToastPrimitive.Description>
              )}
            </div>
            <ToastPrimitive.Close
              aria-label="알림 닫기"
              className="-my-1 flex size-11 shrink-0 items-center justify-center rounded-sm text-text-secondary hover:bg-surface-sunken hover:text-text-primary"
            >
              <X className="size-4" aria-hidden="true" />
            </ToastPrimitive.Close>
          </ToastPrimitive.Root>
        ))}
        <ToastPrimitive.Viewport className="fixed inset-x-4 bottom-[calc(56px+env(safe-area-inset-bottom)+16px)] z-[60] flex flex-col gap-2 outline-none md:inset-x-auto md:right-6 md:bottom-6 md:w-[380px]" />
      </ToastPrimitive.Provider>
    </ToastContext.Provider>
  );
}

export function useToast() {
  const show = useContext(ToastContext);
  if (!show) throw new Error("useToast는 ToastProvider 안에서만 쓸 수 있어요.");
  return show;
}
