import type { GraphEdge, GraphNode } from '@/types/map/graph';

// Synthetic examples, NOT market facts. Company IDs are shared across RDB/Neo4j.
// ERD v6: companies, watchlist, mock_holdings, member_portfolio_connections.
const catalog = [
  ['NASDAQ:NVDA', 'NVIDIA', '#76b900', 'nvidia'],
  ['KRX:005930', '삼성전자', '#1428a0', 'samsung'],
  ['KRX:000660', 'SK하이닉스', '#ea002c', null],
  ['KRX:006400', '삼성SDI', '#1428a0', null],
  ['NYSE:TSM', 'TSMC', '#c4161c', null],
  ['NASDAQ:ASML', 'ASML', '#0b3c8c', null],
  ['KRX:035420', 'NAVER', '#03c75a', 'naver'],
  ['KRX:042700', '한미반도체', '#1428a0', null],
  ['NASDAQ:MU', 'Micron', '#2b6cb0', null],
  ['NASDAQ:TSLA', 'Tesla', '#e82127', 'tesla'],
  ['NASDAQ:AMZN', 'Amazon', '#ff9900', null],
  ['KRX:030200', 'KT', '#ed1c24', null],
  ['NASDAQ:AAPL', 'Apple', '#111111', 'apple'],
  ['NASDAQ:GOOGL', 'Alphabet', '#4285f4', 'alphabet'],
  ['NASDAQ:MSFT', 'Microsoft', '#00a4ef', null],
  ['NASDAQ:META', 'Meta', '#0866ff', 'meta'],
  ['NASDAQ:AMD', 'AMD', '#ed1c24', 'amd'],
  ['NASDAQ:INTC', 'Intel', '#0071c5', 'intel'],
  ['NASDAQ:AVGO', 'Broadcom', '#cc092f', 'broadcom'],
  ['NASDAQ:QCOM', 'Qualcomm', '#3253dc', 'qualcomm'],
  ['NASDAQ:ARM', 'Arm', '#0091bd', 'arm'],
  ['KRX:005380', '현대차', '#002c5f', 'hyundai'],
  ['KRX:035720', '카카오', '#3c1e1e', 'kakao'],
  ['KRX:373220', 'LG에너지솔루션', '#a50034', 'lg'],
] as const;

const nodeDefaults = {
  isFocus: false,
  holding: false,
  watch: false,
  eventTime: null,
  timePrecision: null,
  action: null,
  target: null,
  evidenceCount: null,
  geography: null,
};
export const companies: GraphNode[] = catalog.map(
  ([id, label, brandColor, logo]) => ({
    ...nodeDefaults,
    id,
    kind: 'company',
    label,
    brandColor,
    logoUrl: logo ? `/graph-assets/${logo}.svg` : null,
  }),
);
export const mockMember = {
  memberId: 'mock-member-d-grp',
  holdings: ['KRX:005930', 'NASDAQ:NVDA', 'KRX:035420'],
  watchlist: ['KRX:035420'],
};

// Neo4j Issue/relations: there is intentionally no fictitious PostgreSQL Issue FK.
const cases: [string, string[], 'domestic' | 'international'][] = [
  [
    'HBM4 공급 계약',
    ['KRX:005930', 'NASDAQ:NVDA', 'KRX:000660'],
    'international',
  ],
  [
    'HBM3E 12단 경쟁',
    ['KRX:005930', 'KRX:000660', 'NASDAQ:MU'],
    'international',
  ],
  [
    'ASML 제조 협력 확대',
    ['KRX:005930', 'NASDAQ:ASML', 'NYSE:TSM'],
    'international',
  ],
  ['램프 10억 달러 투자', ['KRX:005930', 'KRX:006400'], 'domestic'],
  ['FSD 칩 위탁 생산', ['KRX:005930', 'NASDAQ:TSLA'], 'international'],
  ['AI 통신망 MOU', ['KRX:035420', 'KRX:030200'], 'domestic'],
  [
    'TSMC 2나노 증설',
    ['NYSE:TSM', 'NASDAQ:AAPL', 'NASDAQ:ASML'],
    'international',
  ],
  [
    '스냅드래곤 엑시노스 경쟁',
    ['NASDAQ:QCOM', 'NASDAQ:ARM', 'NASDAQ:AAPL'],
    'international',
  ],
  [
    'Azure GPU 증설',
    ['NASDAQ:MSFT', 'NASDAQ:AMD', 'NASDAQ:INTC'],
    'international',
  ],
  [
    'AI 서버 투자',
    ['NASDAQ:AMZN', 'NASDAQ:AMD', 'NASDAQ:META'],
    'international',
  ],
  [
    '클라우드 인프라 협력',
    ['NASDAQ:GOOGL', 'NASDAQ:AVGO', 'NASDAQ:MSFT'],
    'international',
  ],
  ['배터리 공급 협력', ['KRX:005380', 'KRX:373220'], 'domestic'],
  ['플랫폼 서비스 협력', ['KRX:035720', 'KRX:030200'], 'domestic'],
  ['반도체 장비 개발', ['KRX:042700', 'KRX:000660'], 'domestic'],
  ['데이터센터 확장', ['NASDAQ:META', 'NASDAQ:INTC'], 'international'],
  ['첨단 패키징 개발', ['NASDAQ:AMD', 'NYSE:TSM'], 'international'],
  ['모바일 칩 설계', ['NASDAQ:ARM', 'NASDAQ:AAPL'], 'international'],
  ['전장 부품 개발', ['KRX:005380', 'KRX:006400'], 'domestic'],
  ...catalog.map(
    ([id, label]) =>
      [
        `${label} 개별 공시 (예시)`,
        [id],
        id.startsWith('KRX') ? 'domestic' : 'international',
      ] as [string, string[], 'domestic' | 'international'],
  ),
  ['미연결 산업 동향 (예시)', [], 'international'],
];
export const issues: GraphNode[] = cases.map(([label, , geography], i) => ({
  ...nodeDefaults,
  id: `mock-issue-${i + 1}`,
  kind: 'issue',
  label,
  brandColor: null,
  logoUrl: null,
  eventTime: '2026-10-06',
  timePrecision: 'day',
  action: 'mock',
  target: label,
  evidenceCount: 1,
  geography,
}));
export const directEdges: GraphEdge[] = cases.flatMap(([, ids], i) =>
  ids.map((id, j) => ({
    id: `mock-relation-${i + 1}-${j + 1}`,
    source: issues[i].id,
    target: id,
    relationType: 'INVOLVES',
    role: 'participant',
    summary: cases[i][0],
    assertionStatus: 'approved',
    derived: false,
    via: [],
    evidenceIds: [`mock-evidence-${i + 1}`],
  })),
);
/** Performance fixture at the server NODE_LIMIT (500): 200 companies, 300 issues. */
export function largeFixture() {
  let seed = 7;
  const next = (n: number) => {
    seed = (seed * 48271) % 2147483647;
    return seed % n;
  };
  const largeCompanies: GraphNode[] = Array.from({ length: 200 }, (_, i) => {
    const [, label, brandColor, logo] = catalog[i % catalog.length];
    // The tutorial guides with 삼성전자, so keep its real ID once.
    const samsung = i === 1;
    return {
      ...nodeDefaults,
      id: samsung ? 'KRX:005930' : `MOCK:${String(i + 1).padStart(3, '0')}`,
      kind: 'company',
      label: samsung ? label : `${label} ${Math.floor(i / catalog.length) + 1}`,
      brandColor,
      logoUrl: logo ? `/graph-assets/${logo}.svg` : null,
    };
  });
  const largeIssues: GraphNode[] = Array.from({ length: 300 }, (_, i) => ({
    ...issues[i % (issues.length - 1)],
    id: `mock-large-issue-${i + 1}`,
    label: `${cases[i % (cases.length - 1)][0]} ${Math.floor(i / (cases.length - 1)) + 1}`,
  }));
  const largeEdges: GraphEdge[] = largeIssues.flatMap((issue, i) => {
    const ids = new Set<string>(i === 0 ? [largeCompanies[1].id] : []);
    const count = 1 + next(3);
    while (ids.size < count) ids.add(largeCompanies[next(200)].id);
    return [...ids].map((id, j) => ({
      id: `mock-large-relation-${i + 1}-${j + 1}`,
      source: issue.id,
      target: id,
      relationType: 'INVOLVES',
      role: 'participant',
      summary: String(issue.label),
      assertionStatus: 'approved',
      derived: false,
      via: [],
      evidenceIds: [`mock-large-evidence-${i + 1}`],
    }));
  });
  return {
    companies: largeCompanies,
    issues: largeIssues,
    directEdges: largeEdges,
  };
}
export const follows: GraphEdge[] = [
  {
    id: 'mock-follows-1',
    source: issues[1].id,
    target: issues[0].id,
    relationType: 'FOLLOWS',
    role: null,
    summary: '후속 개발 (예시)',
    assertionStatus: 'approved',
    derived: false,
    via: [],
    evidenceIds: ['mock-evidence-follow-1'],
  },
];
