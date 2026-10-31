// 자동 생성 파일입니다. 직접 수정하지 마세요. 원본: docs/design/tokens.json (pnpm tokens)

export interface ColorToken {
  name: string;
  tokenPath: string;
  light: string;
  dark: string | null;
  isColor: boolean;
  description: string;
}

export interface ScalarToken {
  name: string;
  tokenPath: string;
  value: string;
  description: string;
}

export const tokenVersion = "3.0.0";
export const colorTokens: ColorToken[] = [
  {
    "name": "brand-primary",
    "tokenPath": "color.brand.primary",
    "light": "#0A5C48",
    "dark": "#47A189",
    "isColor": true,
    "description": "브랜드 딥 스프루스 틸. 화면당 주 행동 1개, 현재 탭·선택 표시에만 쓴다."
  },
  {
    "name": "brand-primary-hover",
    "tokenPath": "color.brand.primary-hover",
    "light": "#0E7059",
    "dark": "#58B198",
    "isColor": true,
    "description": "주 행동 버튼 호버"
  },
  {
    "name": "brand-primary-active",
    "tokenPath": "color.brand.primary-active",
    "light": "#074838",
    "dark": "#36927A",
    "isColor": true,
    "description": "주 행동 버튼 눌림"
  },
  {
    "name": "brand-primary-foreground",
    "tokenPath": "color.brand.primary-foreground",
    "light": "#FFFFFF",
    "dark": "#0A1612",
    "isColor": true,
    "description": "브랜드 배경 위 글자·아이콘"
  },
  {
    "name": "surface-base",
    "tokenPath": "color.neutral.surface-base",
    "light": "#F8FAF9",
    "dark": "#0E1110",
    "isColor": true,
    "description": "앱 배경·그래프 캔버스. 중성은 브랜드 hue(170)로 아주 약하게 기운 회색."
  },
  {
    "name": "surface-raised",
    "tokenPath": "color.neutral.surface-raised",
    "light": "#FFFFFF",
    "dark": "#161918",
    "isColor": true,
    "description": "헤더·패널·사이드바 표면"
  },
  {
    "name": "surface-overlay",
    "tokenPath": "color.neutral.surface-overlay",
    "light": "#FFFFFF",
    "dark": "#1D2220",
    "isColor": true,
    "description": "다이얼로그·시트·팝오버·토스트 표면"
  },
  {
    "name": "surface-sunken",
    "tokenPath": "color.neutral.surface-sunken",
    "light": "#F0F3F2",
    "dark": "#090C0B",
    "isColor": true,
    "description": "세그먼트 배경, 인용문 배경, 중립 배지 배경, 행 호버"
  },
  {
    "name": "surface-selected",
    "tokenPath": "color.neutral.surface-selected",
    "light": "#E4F5EE",
    "dark": "#1A2A25",
    "isColor": true,
    "description": "선택된 행·탭 배경(selected-bg). 텍스트 굵기와 함께 쓴다."
  },
  {
    "name": "border-subtle",
    "tokenPath": "color.neutral.border-subtle",
    "light": "#DFE4E2",
    "dark": "#2B2F2D",
    "isColor": true,
    "description": "행 구분선, 섹션 경계"
  },
  {
    "name": "border-strong",
    "tokenPath": "color.neutral.border-strong",
    "light": "#C2C9C6",
    "dark": "#3E4442",
    "isColor": true,
    "description": "보조 버튼 테두리 등 장식 아닌 경계"
  },
  {
    "name": "border-control",
    "tokenPath": "color.neutral.border-control",
    "light": "#818885",
    "dark": "#6B726F",
    "isColor": true,
    "description": "입력창·체크박스 테두리(비텍스트 대비 3:1 이상)"
  },
  {
    "name": "border-focus",
    "tokenPath": "color.neutral.border-focus",
    "light": "#0A5C48",
    "dark": "#47A189",
    "isColor": true,
    "description": "키보드 포커스 링(2px)"
  },
  {
    "name": "text-primary",
    "tokenPath": "color.neutral.text-primary",
    "light": "#19201D",
    "dark": "#ECEFEE",
    "isColor": true,
    "description": "본문·제목"
  },
  {
    "name": "text-secondary",
    "tokenPath": "color.neutral.text-secondary",
    "light": "#474F4C",
    "dark": "#BABFBD",
    "isColor": true,
    "description": "보조 설명, 발행 시각, 출처"
  },
  {
    "name": "text-tertiary",
    "tokenPath": "color.neutral.text-tertiary",
    "light": "#636B68",
    "dark": "#979D9A",
    "isColor": true,
    "description": "각주, 플레이스홀더, 비활성 글자. 13px 이상에서만."
  },
  {
    "name": "text-inverse",
    "tokenPath": "color.neutral.text-inverse",
    "light": "#FFFFFF",
    "dark": "#0E1110",
    "isColor": true,
    "description": "어두운 배경(툴팁) 위 글자"
  },
  {
    "name": "up",
    "tokenPath": "color.semantic.up",
    "light": "#BE222A",
    "dark": "#EB827B",
    "isColor": true,
    "description": "상승(빨강). 부호 +와 ▲를 함께 쓴다."
  },
  {
    "name": "down",
    "tokenPath": "color.semantic.down",
    "light": "#145EC1",
    "dark": "#79A6E9",
    "isColor": true,
    "description": "하락(파랑). 부호 -와 ▼를 함께 쓴다."
  },
  {
    "name": "warning",
    "tokenPath": "color.semantic.warning",
    "light": "#915C08",
    "dark": "#D9AF75",
    "isColor": true,
    "description": "보류·확인 필요 글자와 아이콘"
  },
  {
    "name": "error",
    "tokenPath": "color.semantic.error",
    "light": "#B21F41",
    "dark": "#EA808A",
    "isColor": true,
    "description": "오류 글자, 오류 입력 테두리"
  },
  {
    "name": "graph-node-issue",
    "tokenPath": "color.graph.node-issue",
    "light": "#4B5652",
    "dark": "#7C8985",
    "isColor": true,
    "description": "사건 노드 범주색(원 하나 + 번개 아이콘). 기업은 상징색을 쓰므로 사건은 채도 없는 한 가지 색으로만 구분한다. 배경 대비 7.3:1, 흰 아이콘 7.6:1."
  },
  {
    "name": "graph-node-glyph",
    "tokenPath": "color.graph.node-glyph",
    "light": "#FFFFFF",
    "dark": "#0E1110",
    "isColor": true,
    "description": "사건 노드 안 아이콘 색"
  },
  {
    "name": "graph-node-mark",
    "tokenPath": "color.graph.node-mark",
    "light": "#19201D",
    "dark": "#ECEFEE",
    "isColor": true,
    "description": "보유·관심 기업 노드의 3px 바깥 테두리(모양 신호)"
  },
  {
    "name": "graph-company-fallback-1",
    "tokenPath": "color.graph.company-fallback.1",
    "light": "#2F6F9F",
    "dark": null,
    "isColor": true,
    "description": "상징색이 없는 기업의 고정 폴백 팔레트. company_id 해시로 고른다(항상 같은 색). 흰 이니셜 대비 4.5:1 이상."
  },
  {
    "name": "graph-company-fallback-2",
    "tokenPath": "color.graph.company-fallback.2",
    "light": "#8A5A2B",
    "dark": null,
    "isColor": true,
    "description": ""
  },
  {
    "name": "graph-company-fallback-3",
    "tokenPath": "color.graph.company-fallback.3",
    "light": "#6B4FA0",
    "dark": null,
    "isColor": true,
    "description": ""
  },
  {
    "name": "graph-company-fallback-4",
    "tokenPath": "color.graph.company-fallback.4",
    "light": "#2E7D5B",
    "dark": null,
    "isColor": true,
    "description": ""
  },
  {
    "name": "graph-company-fallback-5",
    "tokenPath": "color.graph.company-fallback.5",
    "light": "#A2463F",
    "dark": null,
    "isColor": true,
    "description": ""
  },
  {
    "name": "graph-company-fallback-6",
    "tokenPath": "color.graph.company-fallback.6",
    "light": "#5B6B2A",
    "dark": null,
    "isColor": true,
    "description": ""
  },
  {
    "name": "graph-company-fallback-7",
    "tokenPath": "color.graph.company-fallback.7",
    "light": "#2B7A85",
    "dark": null,
    "isColor": true,
    "description": ""
  },
  {
    "name": "graph-company-fallback-8",
    "tokenPath": "color.graph.company-fallback.8",
    "light": "#8E4A78",
    "dark": null,
    "isColor": true,
    "description": ""
  },
  {
    "name": "graph-focus-ring",
    "tokenPath": "color.graph.focus-ring",
    "light": "#0A5C48",
    "dark": "#47A189",
    "isColor": true,
    "description": "선택 노드·간선의 2px 실선 링. 글로우 없음."
  },
  {
    "name": "graph-dimmed-opacity",
    "tokenPath": "color.graph.dimmed-opacity",
    "light": "0.22",
    "dark": "0.22",
    "isColor": false,
    "description": "선택과 무관한 요소의 불투명도. 흐려진 노드는 라벨을 숨기고 호버·포커스 때만 보인다."
  },
  {
    "name": "graph-edge-involves",
    "tokenPath": "color.graph.edge.involves",
    "light": "#2D6359",
    "dark": "#83AFA6",
    "isColor": true,
    "description": "직접 관련: 2px 실선 + 화살표"
  },
  {
    "name": "graph-edge-structurally-related",
    "tokenPath": "color.graph.edge.structurally-related",
    "light": "#626B68",
    "dark": "#8D9491",
    "isColor": true,
    "description": "구조적 관련: 2px 파선 [6,3] + 화살표"
  },
  {
    "name": "graph-edge-follows",
    "tokenPath": "color.graph.edge.follows",
    "light": "#895F34",
    "dark": "#C8A47A",
    "isColor": true,
    "description": "후속 사건: 1.5px 실선 + 화살표"
  },
  {
    "name": "graph-edge-shares-issue",
    "tokenPath": "color.graph.edge.shares-issue",
    "light": "#858B88",
    "dark": "#6D7371",
    "isColor": true,
    "description": "사건 공유(파생): 1.5px 점선 [2,3], 방향 없음"
  },
  {
    "name": "graph-edge-label",
    "tokenPath": "color.graph.edge.label",
    "light": "#474F4C",
    "dark": "#BABFBD",
    "isColor": true,
    "description": "간선 가운데 관계 요약 글자(선을 따라 회전, 배경 surface-base)"
  }
];
export const fontFamilyTokens: ScalarToken[] = [
  {
    "name": "sans",
    "tokenPath": "typography.fontFamily.sans",
    "value": "\"SUIT Variable\", SUIT, -apple-system, BlinkMacSystemFont, \"Apple SD Gothic Neo\", \"Malgun Gothic\", system-ui, sans-serif",
    "description": "프로토타입 값. SUIT Variable(@sun-typeface/suit@2.0.5, OFL-1.1, wght 100~900) 자체 호스팅. KS X 1001 2,668자 밖의 음절은 시스템 한글 서체로 폴백. 서비스 web/은 typography.web.fontFamily를 따른다."
  },
  {
    "name": "mono",
    "tokenPath": "typography.fontFamily.mono",
    "value": "ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace",
    "description": "디자인시스템의 토큰명·경로 표기 전용 시스템 모노 스택(웹폰트 로드 없음)"
  }
];
export const fontSizeTokens: ScalarToken[] = [
  {
    "name": "sm",
    "tokenPath": "typography.fontSize.sm",
    "value": "13px",
    "description": "보조 설명, 발행 시각, 출처, 각주, 법적 고지 하한선 (13px 미만 사용 엄격 금지)"
  },
  {
    "name": "base",
    "tokenPath": "typography.fontSize.base",
    "value": "15px",
    "description": "기본 본문 텍스트 (본문 최소 15px 규칙 충족)"
  },
  {
    "name": "md",
    "tokenPath": "typography.fontSize.md",
    "value": "16px",
    "description": "모바일 폼 입력 필드(iOS 자동 확대 방지 기준), 강조 본문, 버튼 라벨"
  },
  {
    "name": "lg",
    "tokenPath": "typography.fontSize.lg",
    "value": "18px",
    "description": "섹션 헤더, 리스트 제목, 카드 소제목"
  },
  {
    "name": "xl",
    "tokenPath": "typography.fontSize.xl",
    "value": "22px",
    "description": "패널 헤딩, 다이얼로그 타이틀, 종목명 대표 수치"
  },
  {
    "name": "2xl",
    "tokenPath": "typography.fontSize.2xl",
    "value": "28px",
    "description": "화면 메인 제목, 온보딩 대형 헤딩 (화면당 1회 제한)"
  }
];
export const fontWeightTokens: ScalarToken[] = [
  {
    "name": "regular",
    "tokenPath": "typography.fontWeight.regular",
    "value": "400",
    "description": "일반 본문"
  },
  {
    "name": "medium",
    "tokenPath": "typography.fontWeight.medium",
    "value": "500",
    "description": "강조 본문, 폼 라벨, 탭 제목"
  },
  {
    "name": "semibold",
    "tokenPath": "typography.fontWeight.semibold",
    "value": "600",
    "description": "섹션 제목, 리스트 헤더, 종목명"
  },
  {
    "name": "bold",
    "tokenPath": "typography.fontWeight.bold",
    "value": "700",
    "description": "화면 메인 제목, 대표 가격/수치"
  }
];
export const lineHeightTokens: ScalarToken[] = [
  {
    "name": "none",
    "tokenPath": "typography.lineHeight.none",
    "value": "1",
    "description": "아이콘 및 배지 단일 라인"
  },
  {
    "name": "tight",
    "tokenPath": "typography.lineHeight.tight",
    "value": "1.25",
    "description": "대형 헤딩, 대표 수치"
  },
  {
    "name": "snug",
    "tokenPath": "typography.lineHeight.snug",
    "value": "1.375",
    "description": "리스트 제목, 버튼 라벨"
  },
  {
    "name": "normal",
    "tokenPath": "typography.lineHeight.normal",
    "value": "1.5",
    "description": "기본 본문 텍스트"
  },
  {
    "name": "relaxed",
    "tokenPath": "typography.lineHeight.relaxed",
    "value": "1.625",
    "description": "원문 인용구, 긴 서술형 설명"
  }
];
export const spacingTokens: ScalarToken[] = [
  {
    "name": "0",
    "tokenPath": "spacing.0",
    "value": "0px",
    "description": ""
  },
  {
    "name": "1",
    "tokenPath": "spacing.1",
    "value": "4px",
    "description": "초소형 여백, 칩 내부 인라인 간격"
  },
  {
    "name": "2",
    "tokenPath": "spacing.2",
    "value": "8px",
    "description": "소형 여백, 컴포넌트 내부 요소 간 간격"
  },
  {
    "name": "3",
    "tokenPath": "spacing.3",
    "value": "12px",
    "description": "중소형 여백, 버튼 좌우 패딩, 리스트 행 내부 요소 간격"
  },
  {
    "name": "4",
    "tokenPath": "spacing.4",
    "value": "16px",
    "description": "기본 여백 (글로벌 거터), 화면 좌우 여백, 패널 내부 패딩"
  },
  {
    "name": "5",
    "tokenPath": "spacing.5",
    "value": "20px",
    "description": "네비게이션에서 제목까지의 간격"
  },
  {
    "name": "6",
    "tokenPath": "spacing.6",
    "value": "24px",
    "description": "중대형 여백, 섹션 간 간격, 모달 내부 패딩"
  },
  {
    "name": "8",
    "tokenPath": "spacing.8",
    "value": "32px",
    "description": "대형 여백, 페이지 상하 마진"
  },
  {
    "name": "10",
    "tokenPath": "spacing.10",
    "value": "40px",
    "description": "페이지 블록 간격"
  },
  {
    "name": "12",
    "tokenPath": "spacing.12",
    "value": "48px",
    "description": "모바일 하단 터치 안전 여백"
  },
  {
    "name": "16",
    "tokenPath": "spacing.16",
    "value": "64px",
    "description": "온보딩 대형 섹션 간격"
  }
];
export const radiusTokens: ScalarToken[] = [
  {
    "name": "none",
    "tokenPath": "radius.none",
    "value": "0px",
    "description": "목록 행, 섹션, 패널 항목 등 내부 콘텐츠 (카드 박스화 금지, 행+구분선으로 평탄화)"
  },
  {
    "name": "sm",
    "tokenPath": "radius.sm",
    "value": "8px",
    "description": "인터랙티브 컨트롤: 버튼, 텍스트 입력창, 세그먼트 탭 선택 배경"
  },
  {
    "name": "lg",
    "tokenPath": "radius.lg",
    "value": "16px",
    "description": "떠 있는 표면: 바텀시트 상단 모서리, 다이얼로그 모달, 토스트, 팝오버"
  },
  {
    "name": "full",
    "tokenPath": "radius.full",
    "value": "9999px",
    "description": "원형 인터랙티브 컨트롤: 라디오 버튼, 스위치 토글 썸, 원형 노드"
  }
];
export const elevationTokens: ScalarToken[] = [
  {
    "name": "none",
    "tokenPath": "elevation.none",
    "value": "0px 0px 0px 0px transparent",
    "description": "그림자 없음. 테두리가 있는 컨테이너는 항상 이것."
  },
  {
    "name": "raised",
    "tokenPath": "elevation.raised",
    "value": "0px 1px 2px 0px rgba(12, 18, 16, 0.08)",
    "description": "세그먼트 선택 항목처럼 테두리 없는 작은 들린 요소"
  },
  {
    "name": "overlay",
    "tokenPath": "elevation.overlay",
    "value": "0px 4px 16px -2px rgba(12, 18, 16, 0.12)",
    "description": "팝오버·툴팁·토스트(테두리 없이)"
  },
  {
    "name": "modal",
    "tokenPath": "elevation.modal",
    "value": "0px 12px 32px -4px rgba(12, 18, 16, 0.20)",
    "description": "다이얼로그·시트(테두리 없이)"
  }
];
export const motionTokens: ScalarToken[] = [
  {
    "name": "duration.d1",
    "tokenPath": "motion.duration.d1",
    "value": "50ms",
    "description": "SEED $duration.d1"
  },
  {
    "name": "duration.d2",
    "tokenPath": "motion.duration.d2",
    "value": "100ms",
    "description": "SEED $duration.d2"
  },
  {
    "name": "duration.d3",
    "tokenPath": "motion.duration.d3",
    "value": "150ms",
    "description": "SEED $duration.d3 = color-transition = pressed-scale"
  },
  {
    "name": "duration.d4",
    "tokenPath": "motion.duration.d4",
    "value": "200ms",
    "description": "SEED $duration.d4"
  },
  {
    "name": "duration.d5",
    "tokenPath": "motion.duration.d5",
    "value": "250ms",
    "description": "SEED $duration.d5"
  },
  {
    "name": "duration.d6",
    "tokenPath": "motion.duration.d6",
    "value": "300ms",
    "description": "SEED $duration.d6"
  },
  {
    "name": "duration.fast",
    "tokenPath": "motion.duration.fast",
    "value": "150ms",
    "description": "마이크로(=d3): 호버·눌림 색 전환, 눌림 축소, 툴팁·팝오버 등장, 세그먼트 선택 표시"
  },
  {
    "name": "duration.exit",
    "tokenPath": "motion.duration.exit",
    "value": "200ms",
    "description": "매크로 퇴장(=d4): 시트·다이얼로그·토스트가 사라질 때. 등장보다 짧게"
  },
  {
    "name": "duration.normal",
    "tokenPath": "motion.duration.normal",
    "value": "250ms",
    "description": "매크로 등장(=d5): 화면 전환, 시트·다이얼로그 진입, 탭 표시줄 이동, 목록 첫 표시"
  },
  {
    "name": "duration.slow",
    "tokenPath": "motion.duration.slow",
    "value": "300ms",
    "description": "(=d6) 데스크톱 오른쪽 시트 진입, 그래프 선택 시 카메라 팬·줌"
  },
  {
    "name": "duration.graph-layout",
    "tokenPath": "motion.duration.graph-layout",
    "value": "600ms",
    "description": "줍 확장: 그래프 초기 배치·모드 전환 재배치(노드가 제자리로 퍼지는 한 번의 큰 모션)"
  },
  {
    "name": "duration.stagger",
    "tokenPath": "motion.duration.stagger",
    "value": "30ms",
    "description": "줍 확장: 목록 첫 표시 때 행 사이 지연(최대 8행까지만)"
  },
  {
    "name": "easing.linear",
    "tokenPath": "motion.easing.linear",
    "value": "cubic-bezier(0, 0, 1, 1)",
    "description": "SEED $timing-function.linear"
  },
  {
    "name": "easing.standard",
    "tokenPath": "motion.easing.standard",
    "value": "cubic-bezier(0.35, 0, 0.35, 1)",
    "description": "SEED $timing-function.easing: 버튼·입력 포커스 같은 기능적 마이크로 모션, 제자리 이동(세그먼트·탭 표시줄, 그래프 카메라)"
  },
  {
    "name": "easing.enter",
    "tokenPath": "motion.easing.enter",
    "value": "cubic-bezier(0, 0, 0.15, 1)",
    "description": "SEED $timing-function.enter: 다이얼로그·시트·토스트·화면이 나타날 때, 눌림 축소(pressed-scale)"
  },
  {
    "name": "easing.exit",
    "tokenPath": "motion.easing.exit",
    "value": "cubic-bezier(0.35, 0, 1, 1)",
    "description": "SEED $timing-function.exit: 다이얼로그·시트·토스트가 사라질 때"
  },
  {
    "name": "easing.enter-expressive",
    "tokenPath": "motion.easing.enter-expressive",
    "value": "cubic-bezier(0.03, 0.4, 0.1, 1)",
    "description": "SEED $timing-function.enter-expressive: 강조가 필요한 등장(그래프 초기 배치)"
  },
  {
    "name": "easing.exit-expressive",
    "tokenPath": "motion.easing.exit-expressive",
    "value": "cubic-bezier(0.35, 0, 0.95, 0.55)",
    "description": "SEED $timing-function.exit-expressive"
  },
  {
    "name": "press.distance",
    "tokenPath": "motion.press.distance",
    "value": "2px",
    "description": "SEED Feedback/Scale: 눌리면 세로로 2px 줄어든다. 배율 = (basis-2)/basis, basis = max(높이, 폭÷4, 24). 동작 줄이기에서는 축소 없음."
  },
  {
    "name": "reduced.duration",
    "tokenPath": "motion.reduced.duration",
    "value": "0ms",
    "description": "prefers-reduced-motion 활성화 시 즉시 전환"
  }
];
