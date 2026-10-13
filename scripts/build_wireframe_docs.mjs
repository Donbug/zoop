import { createHash } from "node:crypto";
import { copyFileSync, existsSync, mkdirSync, readFileSync, writeFileSync } from "node:fs";
import { basename, join, relative, resolve } from "node:path";

const repoRoot = process.cwd();
const coveragePath = join(
  repoRoot,
  "docs",
  "evidence",
  "raw",
  "wireframe_2026-10-08",
  "coverage.json",
);
const sourcePdf = resolve(repoRoot, process.argv[2] ?? join("..", "zoop-wireframe.pdf"));
const renderedBoards = resolve(
  repoRoot,
  process.argv[3] ?? join("tmp", "pdfs", "zoop-wireframe"),
);
const outputRoot = join(repoRoot, "docs", "wireframe");
const boardsRoot = join(outputRoot, "boards");
const screensRoot = join(outputRoot, "screens");

const sections = [
  {
    sourcePage: 1,
    wireframeSection: "01",
    key: "01-auth-onboarding",
    title: "회원가입·로그인·온보딩",
    nodes: ["619-1080", "619-1208", "619-1429", "619-1509", "619-1615"],
  },
  {
    sourcePage: 2,
    wireframeSection: "02",
    key: "02-map-tutorial",
    title: "지도 튜토리얼",
    nodes: ["619-3337", "619-3920", "619-4508", "619-5095", "619-5682"],
  },
  {
    sourcePage: 3,
    wireframeSection: "03",
    key: "03-map-relationships-evidence",
    title: "지도·관계·근거",
    nodes: [
      "619-1819",
      "619-2374",
      "619-2769",
      "619-6269",
      "619-6729",
      "619-7557",
      "619-8225",
      "619-8880",
      "619-9575",
      "619-10306",
      "619-10871",
    ],
  },
  {
    sourcePage: 4,
    wireframeSection: "03.5",
    key: "03-5-stock-search",
    title: "종목 탐색",
    nodes: ["692-2"],
  },
  {
    sourcePage: 5,
    wireframeSection: "04",
    key: "04-company-detail",
    title: "기업 상세·시점 탐색",
    nodes: ["637-2222", "637-6212", "658-7834", "658-8442", "663-14180", "663-13515"],
  },
  {
    sourcePage: 6,
    wireframeSection: "05",
    key: "05-briefing",
    title: "출퇴근 브리핑",
    nodes: ["620-948", "620-1278", "730-278"],
  },
  {
    sourcePage: 7,
    wireframeSection: "06",
    key: "06-ai-chat",
    title: "AI 질문·대화 상태",
    nodes: ["620-1593", "620-3770", "620-4314", "620-4859"],
  },
  {
    sourcePage: 8,
    wireframeSection: "09",
    key: "09-admin",
    title: "관리자 운영",
    nodes: [
      "620-8120",
      "620-8166",
      "620-8616",
      "620-8960",
      "620-9307",
      "620-9769",
      "620-10181",
      "620-10650",
      "620-10924",
    ],
  },
];

const titleOverrides = new Map([
  ["692-2", "D-STK-01 · 종목 탐색"],
  ["637-2222", "D-COM-01 · 기업 상세·시세·모의 보유"],
  ["637-6212", "D-COM-01b · 차트·시간 버킷·인과관계 고지"],
  ["658-7834", "D-COM-02 · 문서 탭 전환 — 상태 확인 필요"],
  ["658-8442", "D-COM-05/06 · 버킷·차트·그래프 연동·주가 그래프 시점 선택"],
  ["730-278", "D-BRF-04 · 회차 기준 지도"],
]);

const coverage = JSON.parse(readFileSync(coveragePath, "utf8"));
const framesByNode = new Map(coverage.frames.map((frame) => [frame.node, frame]));

mkdirSync(boardsRoot, { recursive: true });
mkdirSync(screensRoot, { recursive: true });

const records = [];
const boardRecords = [];

for (const section of sections) {
  const sourceBoard = join(renderedBoards, `board-${section.sourcePage}.jpg`);
  const boardFile = `${section.key}.jpg`;
  const outputBoard = join(boardsRoot, boardFile);
  if (existsSync(sourceBoard)) {
    copyFileSync(sourceBoard, outputBoard);
  } else if (!existsSync(outputBoard)) {
    throw new Error(
      `Missing rendered board: ${sourceBoard}. Pass the rendered board directory as the second argument.`,
    );
  }
  boardRecords.push({
    sourcePage: section.sourcePage,
    wireframeSection: section.wireframeSection,
    key: section.key,
    title: section.title,
    image: `boards/${boardFile}`,
    frameCount: section.nodes.length,
  });

  for (const [position, node] of section.nodes.entries()) {
    const frame = framesByNode.get(node);
    if (!frame) {
      throw new Error(`Coverage does not contain node ${node}`);
    }

    const idPart = frame.screenIds.join("_");
    const imageFile = `${idPart}--node-${node}.png`;
    const sourceImage = join(repoRoot, ...frame.path.split("/"));
    if (!existsSync(sourceImage)) {
      throw new Error(`Missing frame image: ${sourceImage}`);
    }
    copyFileSync(sourceImage, join(screensRoot, imageFile));

    const specFiles = frame.screenIds
      .map((screenId) => `docs/system/out/screen-${screenId}.md`)
      .filter((path) => existsSync(join(repoRoot, ...path.split("/"))));

    records.push({
      section: section.key,
      sectionTitle: section.title,
      sourcePage: section.sourcePage,
      wireframeSection: section.wireframeSection,
      position: position + 1,
      screenIds: frame.screenIds,
      title: titleOverrides.get(node) ?? frame.name,
      image: `screens/${imageFile}`,
      node: frame.node,
      figmaUrl: frame.url,
      routes: [...new Set((frame.baseline ?? []).map((item) => item.route).filter(Boolean))],
      baselinePages: [...new Set((frame.baseline ?? []).map((item) => item.page).filter(Boolean))],
      specFiles,
      staticVisual: frame.staticVisual,
      interaction: frame.interaction,
      annotationState: frame.annotationState,
      mappingBasis: frame.mappingBasis,
      sourceImage: frame.path,
    });
  }
}

const sourceSha256 = createHash("sha256").update(readFileSync(sourcePdf)).digest("hex");
const uniqueScreenIds = [...new Set(records.flatMap((record) => record.screenIds))].sort();
const manifest = {
  schemaVersion: 1,
  generatedAt: "2026-10-13",
  source: {
    fileName: basename(sourcePdf),
    sha256: sourceSha256,
    pageCount: sections.length,
    boardRender: "JPEG, 54 DPI, quality 85; overview only",
    individualFrames: "PNG copied from the repository wireframe evidence set",
  },
  counts: {
    sections: sections.length,
    frames: records.length,
    uniqueScreenIds: uniqueScreenIds.length,
  },
  screenIds: uniqueScreenIds,
  boards: boardRecords,
  screens: records,
};

writeFileSync(join(outputRoot, "manifest.json"), `${JSON.stringify(manifest, null, 2)}\n`, "utf8");

const md = [];
md.push("# ZOOP 와이어프레임 개발 참조");
md.push("");
md.push("> 첨부된 `zoop-wireframe.pdf`의 8개 보드를 개발 중 검색·참조하기 쉬운 형태로 정리한 자료입니다.");
md.push("");
md.push("## 사용 방법");
md.push("");
md.push("- 화면을 구현하거나 수정하기 전에 화면 ID로 이 문서와 `manifest.json`을 검색합니다.");
md.push("- 전체 흐름은 `boards/`, 실제 UI 디테일은 `screens/`의 개별 PNG를 기준으로 확인합니다.");
md.push("- `manifest.json`의 `routes`는 기존 화면계획서의 기준 경로이며, 시각 이미지가 동작 완료를 증명하지는 않습니다.");
md.push("- 화면에 명시되지 않은 오류·로딩·빈 상태나 상호작용은 임의로 확정하지 말고 관련 요구사항·화면계획서와 함께 확인합니다.");
md.push("");
md.push("## 파일 구성");
md.push("");
md.push("| 경로 | 용도 |");
md.push("|---|---|");
md.push("| `manifest.json` | 화면 ID, 섹션, 순서, 라우트, Figma node를 담은 기계 판독용 인덱스 |");
md.push("| `boards/*.jpg` | PDF 페이지 전체 흐름을 빠르게 보는 보드 이미지 |");
md.push("| `screens/*.png` | 구현 시 확대해 보는 개별 화면 원본 |");
md.push("");
md.push(`현재 범위: **${sections.length}개 섹션 · ${records.length}개 프레임 · ${uniqueScreenIds.length}개 고유 화면 ID**`);
md.push("");
md.push("첨부본에 없는 디자인시스템(07)·모바일(08) 화면은 이 폴더의 범위에 포함하지 않았습니다.");
md.push("");

for (const section of sections) {
  const board = boardRecords.find((item) => item.key === section.key);
  md.push(`## ${section.wireframeSection} · ${section.title}`);
  md.push("");
  md.push(`[전체 보드 보기](${board.image})`);
  md.push("");
md.push("| 순서 | 화면 ID | 화면명 | 기준 라우트 | 이미지 | 상세 문서 |");
md.push("|---:|---|---|---|---|---|");
  for (const record of records.filter((item) => item.section === section.key)) {
    const ids = record.screenIds.map((id) => `\`${id}\``).join(", ");
    const routes = record.routes.length
      ? record.routes.map((route) => `\`${route.replaceAll("|", "\\|")}\``).join("<br>")
      : "-";
    const specs = record.specFiles.length
      ? record.specFiles
          .map((path) => `[${basename(path, ".md").replace("screen-", "")}](${relative(outputRoot, join(repoRoot, ...path.split("/"))).replaceAll("\\", "/")})`)
          .join("<br>")
      : "-";
    md.push(
      `| ${record.position} | ${ids} | ${record.title.replaceAll("|", "\\|")} | ${routes} | [PNG](${record.image}) | ${specs} |`,
    );
  }
  md.push("");
}

md.push("## 원본과 갱신");
md.push("");
md.push(`- 원본 파일: \`${basename(sourcePdf)}\``);
md.push(`- SHA-256: \`${sourceSha256}\``);
md.push("- 개별 화면은 `docs/evidence/raw/wireframe_2026-10-08/coverage.json`의 화면 ID·node 대응을 사용했습니다.");
md.push("- 새 와이어프레임으로 교체할 때는 화면 ID를 유지하고, `manifest.json`과 이 인덱스를 함께 갱신합니다.");
md.push("");

writeFileSync(join(outputRoot, "README.md"), `${md.join("\n")}\n`, "utf8");

console.log(
  JSON.stringify(
    {
      output: relative(repoRoot, outputRoot),
      boards: boardRecords.length,
      frames: records.length,
      uniqueScreenIds: uniqueScreenIds.length,
      sourceSha256,
    },
    null,
    2,
  ),
);
