import { useEffect, useId, useRef, useState } from 'react';
import GraphIcon from './GraphIcon';

// D-GRP-01 16번 조작 도움말. 기업·사건 고르기는 지도 안의 기존 키보드 목록(범례 숨김·포커스를 따름)을 안내만 한다.
// 팝오버 안에는 버튼을 두지 않는다: .relationship-toolbar-help button 규칙이 안쪽 버튼까지 덮는다.
export default function GraphHelp({ disabled }: { disabled: boolean }) {
  const [open, setOpen] = useState(false);
  const root = useRef<HTMLDivElement>(null);
  const trigger = useRef<HTMLButtonElement>(null);
  const id = useId();
  useEffect(() => {
    if (!open) return;
    const closeOutside = (event: PointerEvent) => {
      if (event.target instanceof Node && !root.current?.contains(event.target))
        setOpen(false);
    };
    document.addEventListener('pointerdown', closeOutside);
    return () => document.removeEventListener('pointerdown', closeOutside);
  }, [open]);
  return (
    <div
      ref={root}
      onKeyDown={(event) => {
        if (open && event.key === 'Escape') {
          event.preventDefault();
          event.stopPropagation();
          setOpen(false);
          trigger.current?.focus();
        }
      }}
    >
      <button
        ref={trigger}
        type="button"
        aria-label="조작 도움말"
        className="max-md:min-h-10 max-md:min-w-10"
        aria-expanded={open}
        aria-controls={open ? id : undefined}
        disabled={disabled}
        onClick={() => setOpen((value) => !value)}
      >
        <GraphIcon name="help" size={19} />
      </button>
      {open && (
        <div
          id={id}
          role="region"
          aria-label="지도 조작 도움말"
          className="fixed top-24 right-4 z-50 w-80 max-w-[calc(100vw-2rem)] rounded-panel border border-zoop-line bg-zoop-paper p-4 text-left text-xs text-zoop-ink shadow-lg"
        >
          <p className="font-bold">지도 둘러보기</p>
          <p className="mt-2 leading-relaxed">
            끌어서 지도를 이동하고 휠 또는 확대·축소 버튼으로 크기를 바꿔요.
            기업·사건을 두 번 누르거나 Shift+Enter를 누르면 이웃으로 확대해요.
            키보드로는 Tab으로 지도 안의 기업·사건·연결선 목록을 이동하고
            Enter로 골라요. Escape로 도움말을 닫아요.
          </p>
        </div>
      )}
    </div>
  );
}
