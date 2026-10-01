// docs/design/tokens.json(단일 원천)을 읽어 두 파일을 만든다.
//   src/styles/tokens.css          — CSS 변수 + Tailwind v4 @theme (라이트/다크)
//   src/styles/tokens.generated.ts — 디자인시스템 페이지가 표로 보여줄 토큰 목록
// 두 파일은 자동 생성물이므로 직접 고치지 말고 tokens.json을 고친 뒤 `pnpm tokens`를 실행한다.
// `pnpm dev`, `pnpm build`, `pnpm typecheck`는 이 스크립트를 먼저 자동 실행한다.

import { readFileSync, writeFileSync, mkdirSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const here = dirname(fileURLToPath(import.meta.url));
const tokensPath = resolve(here, "../../../docs/design/tokens.json");
const outCss = resolve(here, "../src/styles/tokens.css");
const outTs = resolve(here, "../src/styles/tokens.generated.ts");

const tokens = JSON.parse(readFileSync(tokensPath, "utf8"));

/** DTCG 값(문자열/숫자/차원 객체/그림자 객체/큐빅 베지어 배열)을 CSS 문자열로 바꾼다. */
function toCss(value, type) {
  if (typeof value === "number") return String(value);
  if (typeof value === "string") return value;
  if (Array.isArray(value)) {
    if (type === "cubicBezier" || value.every((v) => typeof v === "number")) {
      return `cubic-bezier(${value.join(", ")})`;
    }
    return value.map((v) => (/\s/.test(v) ? `"${v}"` : v)).join(", ");
  }
  if (value && typeof value === "object") {
    if ("value" in value && "unit" in value) return `${value.value}${value.unit}`;
    if ("offsetX" in value) {
      return [value.offsetX, value.offsetY, value.blur, value.spread, value.color].map((v) => toCss(v)).join(" ");
    }
  }
  throw new Error(`알 수 없는 토큰 값 형식: ${JSON.stringify(value)}`);
}

/** 그룹 트리를 {path, value, type, description} 목록으로 편다. $type은 하위로 상속된다. */
function flatten(node, path = [], inheritedType) {
  const type = node.$type ?? inheritedType;
  if (node && typeof node === "object" && "$value" in node) {
    return [{ path, value: node.$value, type, description: node.$description ?? "" }];
  }
  return Object.entries(node).flatMap(([key, child]) =>
    key.startsWith("$") || typeof child !== "object" || child === null ? [] : flatten(child, [...path, key], type),
  );
}

// 색 이름 규칙: color.<그룹>.<이름> → <그룹>-<이름>. 단 neutral·semantic 그룹 이름은 생략한다.
//   color.neutral.text-primary → text-primary  (Tailwind: text-text-primary, bg-surface-base …)
//   color.semantic.up.text     → up-text       (Tailwind: text-up-text)
//   color.graph.edge.involves  → graph-edge-involves
const dropGroups = new Set(["neutral", "semantic"]);
const colorName = (path) => path.filter((p) => !dropGroups.has(p)).join("-");

const { dark, ...lightColors } = tokens.color;
const light = flatten(lightColors, [], tokens.color.$type);
const darkByName = new Map(flatten(dark ?? {}, [], tokens.color.$type).map((t) => [colorName(t.path), t]));

const colors = light.map((t) => {
  const name = colorName(t.path);
  const d = darkByName.get(name);
  return {
    name,
    tokenPath: ["color", ...t.path].join("."),
    light: toCss(t.value, t.type),
    dark: d ? toCss(d.value, d.type) : null,
    isColor: typeof t.value === "string",
    description: t.description,
  };
});
for (const name of darkByName.keys()) {
  if (!colors.some((c) => c.name === name)) throw new Error(`다크 토큰 ${name}에 대응하는 라이트 토큰이 없습니다.`);
}

const group = (key) => flatten(tokens[key] ?? {}, [], tokens[key]?.$type);
const typo = tokens.typography;
const fontFamily = flatten(typo.fontFamily, [], typo.fontFamily.$type);
const fontSize = flatten(typo.fontSize, [], typo.fontSize.$type);
const fontWeight = flatten(typo.fontWeight, [], typo.fontWeight.$type);
const lineHeight = flatten(typo.lineHeight, [], typo.lineHeight.$type);
const letterSpacing = flatten(typo.letterSpacing, [], typo.letterSpacing.$type);
const spacing = group("spacing");
const radius = group("radius");
const elevation = group("elevation");
const motion = group("motion");

const line = (name, value) => `  ${name}: ${value};`;
const css = [];
css.push("/* 자동 생성 파일입니다. 직접 수정하지 마세요.");
css.push(" * 원본: docs/design/tokens.json → 수정 후 `pnpm tokens` (dev/build 시 자동 실행) */");
css.push("");
css.push(":root {");
css.push("  color-scheme: light;");
for (const c of colors) css.push(line(`--zoop-${c.name}`, c.light));
for (const t of motion) css.push(line(`--zoop-motion-${t.path.join("-")}`, toCss(t.value, t.type)));
css.push("}");
css.push("");
css.push(':root[data-theme="dark"] {');
css.push("  color-scheme: dark;");
for (const c of colors) if (c.dark) css.push(line(`--zoop-${c.name}`, c.dark));
css.push("}");
css.push("");
css.push("/* 사용자가 '동작 줄이기'를 켜면 모든 전환 시간을 0으로 만든다. */");
css.push("@media (prefers-reduced-motion: reduce) {");
css.push("  :root {");
for (const t of motion.filter((m) => m.path[0] === "duration")) {
  css.push(`  ${line(`--zoop-motion-${t.path.join("-")}`, toCss(tokens.motion.reduced.duration.$value))}`);
}
css.push("  }");
css.push("}");
css.push("");
css.push("@theme {");
css.push("  --color-*: initial;");
css.push("  --text-*: initial;");
css.push("  --shadow-*: initial;");
css.push("  --radius-*: initial;");
for (const t of fontFamily) css.push(line(`--font-${t.path.join("-")}`, toCss(t.value)));
for (const t of fontSize) css.push(line(`--text-${t.path.join("-")}`, toCss(t.value)));
for (const t of fontWeight) css.push(line(`--font-weight-${t.path.join("-")}`, toCss(t.value)));
for (const t of lineHeight) css.push(line(`--leading-${t.path.join("-")}`, toCss(t.value)));
for (const t of letterSpacing) css.push(line(`--tracking-${t.path.join("-")}`, toCss(t.value)));
const spacingUnit = spacing.find((t) => t.path[0] === "1");
if (spacingUnit) css.push(line("--spacing", toCss(spacingUnit.value)));
for (const t of radius) css.push(line(`--radius-${t.path.join("-")}`, toCss(t.value)));
for (const t of elevation) css.push(line(`--shadow-${t.path.join("-")}`, toCss(t.value)));
for (const t of motion.filter((m) => m.path[0] === "easing")) css.push(line(`--ease-${t.path[1]}`, toCss(t.value, t.type)));
css.push("}");
css.push("");
css.push("/* 색은 테마에 따라 바뀌므로 변수 참조(inline)로 연결한다. */");
css.push("@theme inline {");
for (const c of colors) if (c.isColor) css.push(line(`--color-${c.name}`, `var(--zoop-${c.name})`));
css.push("}");
css.push("");

const list = (items, prefix) =>
  items.map((t) => ({ name: t.path.join("."), tokenPath: [prefix, ...t.path].join("."), value: toCss(t.value, t.type), description: t.description }));

const ts = `// 자동 생성 파일입니다. 직접 수정하지 마세요. 원본: docs/design/tokens.json (pnpm tokens)

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

export const tokenVersion = ${JSON.stringify(tokens.version ?? "")};
export const colorTokens: ColorToken[] = ${JSON.stringify(colors, null, 2)};
export const fontFamilyTokens: ScalarToken[] = ${JSON.stringify(list(fontFamily, "typography.fontFamily"), null, 2)};
export const fontSizeTokens: ScalarToken[] = ${JSON.stringify(list(fontSize, "typography.fontSize"), null, 2)};
export const fontWeightTokens: ScalarToken[] = ${JSON.stringify(list(fontWeight, "typography.fontWeight"), null, 2)};
export const lineHeightTokens: ScalarToken[] = ${JSON.stringify(list(lineHeight, "typography.lineHeight"), null, 2)};
export const spacingTokens: ScalarToken[] = ${JSON.stringify(list(spacing, "spacing"), null, 2)};
export const radiusTokens: ScalarToken[] = ${JSON.stringify(list(radius, "radius"), null, 2)};
export const elevationTokens: ScalarToken[] = ${JSON.stringify(list(elevation, "elevation"), null, 2)};
export const motionTokens: ScalarToken[] = ${JSON.stringify(list(motion, "motion"), null, 2)};
`;

mkdirSync(dirname(outCss), { recursive: true });
writeFileSync(outCss, css.join("\n"));
writeFileSync(outTs, ts);
console.log(`토큰 생성 완료: 색 ${colors.length}개 → src/styles/tokens.css, src/styles/tokens.generated.ts`);
