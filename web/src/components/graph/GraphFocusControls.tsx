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
      className="absolute top-4 left-9 z-10 flex h-10 items-center rounded-panel border border-panel-line bg-white p-1 font-panel text-[11px] shadow-[0_4px_16px_rgb(0_0_0/0.08)]"
      aria-label={`${label} 중심 보기`}
    >
      <strong className="max-w-32 truncate px-2 text-[12px] font-semibold">
        {label} 중심
      </strong>
      <span className="mx-1 h-5 w-px bg-panel-line" aria-hidden="true" />
      {([1, 2] as const).map((value) => (
        <label
          key={value}
          className={`grid h-8 cursor-pointer place-items-center rounded-panel px-2.5 font-semibold ${hops === value ? 'bg-panel-ink text-white' : 'text-panel-secondary hover:bg-panel-soft'}`}
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
        className="ml-1 h-8 rounded-panel border border-panel-line px-3 font-semibold hover:bg-panel-soft"
        onClick={onClear}
      >
        전체 보기
      </button>
    </div>
  );
}
