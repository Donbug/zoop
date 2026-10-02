// FS044(D06) 그래프 ↔ 기업 상세 왕복에서 '진입 그래프' 상태를 보관하는 형식.
//  - 그래프(메인) 화면은 떠날 때 마지막 상태(주소 + 카메라)를 저장한다(saveGraphEntry).
//  - 기업 상세는 그래프에서 들어왔을 때 그 값을 잡아 두고, 「그래프로 복귀」는 그 주소로 이동하며 state.graphRestore로 넘긴다.
//    진입 그래프가 없으면(직접 주소·내 종목·브리핑에서 진입) 전체 관계 그래프(FULL_GRAPH_URL)를 연다.
//  - 브라우저 뒤로 가기는 실제 이력을 따르며 이 값을 쓰지 않는다. 새로고침·다른 기기 복원은 범위 밖(sessionStorage).
//  - FS019 모드 전환: 같은 형식으로 모드마다 떠날 때의 상태(주소 + 카메라 + 범례 필터)를 따로 보관하고(saveModeEntry),
//    그 모드로 돌아오면 복원한다(readModeEntry). 같은 탭 세션 동안만 유지한다.
export interface GraphCamera {
  zoom: number;
  pan: { x: number; y: number };
}

export interface GraphEntry {
  /** 그래프 화면 주소(pathname + search). 모드·선택·focus·필터를 담는다. */
  url: string;
  camera?: GraphCamera;
  /** 범례로 끈 항목(LegendKey) */
  hidden?: string[];
  view?: "graph" | "list";
}

/** 메인 화면에 `navigate(entry.url, { state: { graphRestore: entry } })`로 넘기는 state 모양 */
export interface GraphRestoreState {
  graphRestore: GraphEntry;
}

export const FULL_GRAPH_URL = "/?mode=all";
const KEY = "zoop:graph-entry";

function isEntry(value: unknown): value is GraphEntry {
  if (!value || typeof value !== "object") return false;
  const v = value as Record<string, unknown>;
  return typeof v.url === "string" && v.url.startsWith("/") && !v.url.startsWith("//");
}

export function saveGraphEntry(entry: GraphEntry): void {
  try {
    sessionStorage.setItem(KEY, JSON.stringify(entry));
  } catch {
    // 저장소를 쓸 수 없으면 복귀 버튼이 전체 그래프로 간다.
  }
}

export function readGraphEntry(): GraphEntry | null {
  try {
    const raw = sessionStorage.getItem(KEY);
    const parsed: unknown = raw ? JSON.parse(raw) : null;
    return isEntry(parsed) ? parsed : null;
  } catch {
    return null;
  }
}

const MODE_KEY_PREFIX = "zoop:graph-mode:";

export function saveModeEntry(mode: string, entry: GraphEntry): void {
  try {
    sessionStorage.setItem(MODE_KEY_PREFIX + mode, JSON.stringify(entry));
  } catch {
    // 저장소를 쓸 수 없으면 그 모드로 돌아왔을 때 처음 상태(화면 맞춤)로 연다.
  }
}

export function readModeEntry(mode: string): GraphEntry | null {
  try {
    const raw = sessionStorage.getItem(MODE_KEY_PREFIX + mode);
    const parsed: unknown = raw ? JSON.parse(raw) : null;
    return isEntry(parsed) ? parsed : null;
  } catch {
    return null;
  }
}

/** 주소가 그래프(메인) 화면인지: pathname이 '/'인 주소 */
export function isGraphUrl(url: string): boolean {
  return url === "/" || url.startsWith("/?");
}
