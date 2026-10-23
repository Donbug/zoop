type Props = {
  label: string;
  hops: 1 | 2;
  onHopsChange: (hops: 1 | 2) => void;
  onClear: () => void;
};

// WBS 6.6.26 · D-GRP-07b · Figma 619:10306
export default function GraphFocusControls({
  label,
  hops,
  onHopsChange,
  onClear,
}: Props) {
  return (
    <div
      data-screen-id="D-GRP-07b"
      role="group"
      className="absolute top-4 left-9 z-10 flex min-h-11 max-w-[calc(100%-1rem)] items-center rounded-panel border border-zoop-line bg-zoop-paper p-1 font-panel text-[13px] text-zoop-ink shadow-sm max-md:top-2 max-md:left-2"
      aria-label={`${label} 중심 보기`}
    >
      <strong className="max-w-32 truncate px-2 text-[13px] font-semibold max-md:max-w-24">
        {label} 중심
      </strong>
      <span className="mx-1 h-5 w-px bg-panel-line" aria-hidden="true" />
      {([1, 2] as const).map((value) => (
        <label
          key={value}
          className={`grid h-8 cursor-pointer place-items-center rounded-panel px-2.5 font-semibold max-md:min-h-11 ${hops === value ? 'bg-zoop-ink text-zoop-paper' : 'text-zoop-muted hover:bg-zoop-soft'}`}
        >
          <input
            className="sr-only"
            type="radio"
            name="focus-hops"
            checked={hops === value}
            onChange={() => onHopsChange(value)}
            aria-label={`${value}단계: ${value === 1 ? '직접 이웃까지' : '이웃의 이웃까지'}`}
          />
          {value}단계
        </label>
      ))}
      <button
        className="ml-1 h-8 rounded-panel border border-zoop-line px-3 font-semibold hover:bg-zoop-soft max-md:min-h-11"
        onClick={onClear}
      >
        전체 보기
      </button>
    </div>
  );
}
