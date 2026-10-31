import GraphIcon from '@/components/graph/GraphIcon';

// D-AUT-01 시작 화면의 서비스 소개. 지도 그림은 실제 자료가 아닌 예시이며 그렇게 표기한다.
const COMPANIES = [
  { id: 'sk', label: 'SK하이닉스', logo: 'sk-hynix', x: 132, y: 64 },
  { id: 'nvda', label: 'NVIDIA', logo: 'nvidia', x: 372, y: 58, holding: true },
  { id: 'samsung', label: '삼성전자', logo: 'samsung', x: 84, y: 196 },
  { id: 'tsmc', label: 'TSMC', logo: 'tsmc', x: 262, y: 246 },
  { id: 'amd', label: 'AMD', logo: 'amd', x: 478, y: 128 },
];
const ISSUES = [
  { id: 'hbm', label: 'HBM 공급 계약', x: 236, y: 132, below: false },
  { id: 'gpu', label: 'AI 가속기 출시', x: 368, y: 190, below: true },
];
const LINKS = [
  ['sk', 'hbm'],
  ['nvda', 'hbm'],
  ['samsung', 'hbm'],
  ['nvda', 'gpu'],
  ['amd', 'gpu'],
  ['tsmc', 'gpu'],
];
const SHARED = [['sk', 'nvda']];

const FEATURES = [
  {
    icon: 'map',
    title: '사건 지도',
    text: '기업과 사건이 어떻게 이어지는지 지도에서 한눈에 확인해요.',
  },
  {
    icon: 'issue',
    title: '근거 확인',
    text: '모든 연결에 출처가 되는 기사와 공시를 함께 보여 줘요.',
  },
  {
    icon: 'briefing',
    title: '브리핑과 AI 질문',
    text: '관심 종목 소식을 요약하고, 궁금한 점은 근거와 함께 답해요.',
  },
];

const point = (id: string) =>
  COMPANIES.find((c) => c.id === id) ?? ISSUES.find((i) => i.id === id)!;

function ExampleMap() {
  return (
    <figure className="relative m-0 overflow-hidden rounded-[3px] border-[0.667px] border-zoop-line bg-zoop-paper">
      <figcaption className="absolute top-3 left-3 rounded-full border-[0.667px] border-zoop-line bg-zoop-wash px-2 py-0.5 text-caption text-zoop-muted">
        예시 화면
      </figcaption>
      <svg
        viewBox="0 0 540 300"
        className="block h-auto w-full"
        role="img"
        aria-label="기업과 사건을 잇는 지도 예시: SK하이닉스·NVIDIA·삼성전자가 HBM 공급 계약으로, NVIDIA·AMD·TSMC가 AI 가속기 출시로 이어져 있어요."
      >
        <defs>
          {COMPANIES.map((c) => (
            <clipPath key={c.id} id={`intro-logo-${c.id}`}>
              <circle cx={c.x} cy={c.y} r={20} />
            </clipPath>
          ))}
        </defs>
        {SHARED.map(([a, b]) => (
          <line
            key={`${a}-${b}`}
            x1={point(a).x}
            y1={point(a).y}
            x2={point(b).x}
            y2={point(b).y}
            strokeDasharray="4 4"
            className="stroke-zoop-faint"
          />
        ))}
        {LINKS.map(([a, b]) => (
          <line
            key={`${a}-${b}`}
            x1={point(a).x}
            y1={point(a).y}
            x2={point(b).x}
            y2={point(b).y}
            className="stroke-zoop-line"
            strokeWidth={1.5}
          />
        ))}
        {ISSUES.map((i) => (
          <g key={i.id}>
            <rect
              x={i.x - 7}
              y={i.y - 7}
              width={14}
              height={14}
              transform={`rotate(45 ${i.x} ${i.y})`}
              className="fill-zoop-ink"
            />
            <text
              x={i.below ? i.x : i.x + 14}
              y={i.below ? i.y + 26 : i.y + 4}
              textAnchor={i.below ? 'middle' : 'start'}
              className="fill-zoop-ink text-caption font-semibold"
            >
              {i.label}
            </text>
          </g>
        ))}
        {COMPANIES.map((c) => (
          <g key={c.id}>
            <circle
              cx={c.x}
              cy={c.y}
              r={22}
              className={
                c.holding
                  ? 'fill-zoop-paper stroke-zoop-ink'
                  : 'fill-zoop-paper stroke-zoop-line'
              }
              strokeWidth={c.holding ? 2 : 1}
            />
            <image
              href={`/graph-assets/${c.logo}.svg`}
              x={c.x - 20}
              y={c.y - 20}
              width={40}
              height={40}
              preserveAspectRatio="xMidYMid slice"
              clipPath={`url(#intro-logo-${c.id})`}
            />
            <text
              x={c.x}
              y={c.y + 36}
              textAnchor="middle"
              className="fill-zoop-muted text-caption"
            >
              {c.holding ? `${c.label} · 보유` : c.label}
            </text>
          </g>
        ))}
      </svg>
    </figure>
  );
}

export default function ServiceIntro() {
  return (
    <aside aria-labelledby="intro-title" className="flex flex-col gap-6">
      <div className="border-b-[0.667px] border-zoop-line pb-4">
        <p className="text-display font-[750] tracking-[-0.045em] text-zoop-ink font-heading">
          ZOOP
        </p>
        <p className="mt-1.5 text-caption text-zoop-muted">
          내 종목 주변의 사건과 근거를 탐색해요
        </p>
      </div>
      <div>
        <p className="text-caption font-semibold tracking-[0.02em] text-zoop-muted">
          사건으로 읽는 종목 지도
        </p>
        <h2
          id="intro-title"
          className="mt-2 text-display leading-[1.3] font-[750] tracking-[-0.04em] text-zoop-ink lg:text-display"
        >
          내 종목 주변에서 일어난 일을
          <br />
          하나의 그래프로 한눈에 봐요
        </h2>
        <p className="mt-3 max-w-[520px] text-body leading-[1.6] text-zoop-muted">
          공시와 기사에서 확인된 사건을 기업과 이어, 어떤 일이 어떤 근거로 내
          종목과 연결되는지 보여 줘요.
        </p>
      </div>
      <div className="max-lg:hidden">
        <ExampleMap />
      </div>
      <ul className="m-0 grid list-none gap-4 p-0 max-lg:hidden lg:grid-cols-3">
        {FEATURES.map((f) => (
          <li key={f.title} className="flex flex-col gap-1.5">
            <span className="grid size-7 place-items-center rounded-full bg-zoop-soft">
              <GraphIcon name={f.icon} size={14} />
            </span>
            <strong className="text-caption font-bold text-zoop-ink">
              {f.title}
            </strong>
            <p className="text-caption leading-[1.55] text-zoop-muted">
              {f.text}
            </p>
          </li>
        ))}
      </ul>
    </aside>
  );
}
