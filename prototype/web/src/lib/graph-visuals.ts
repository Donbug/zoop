// 그래프 노드의 색·글리프(로고/이니셜/아이콘) 계산. GraphCanvas와 범례·목록의 기업 표지가 같이 쓴다.
//  - 기업: 상징색(brandColor) 원 + 대비가 나은 색(흰색/거의 검정)의 로고 실루엣. 로고가 없으면 이니셜.
//    상징색이 없으면 토큰의 고정 폴백 팔레트(graph-company-fallback-1..8)에서 company_id 해시로 고른다.
//  - 사건: 범주색(graph-node-issue) 원 하나 + 번개 아이콘.
// 글리프 이미지는 한 번 만들면 (색·로고·글자) 키로 캐시한다.

export const FALLBACK_PALETTE_SIZE = 8;

function cssVar(name: string) {
  return getComputedStyle(document.documentElement).getPropertyValue(`--zoop-${name}`).trim();
}

/** 같은 id면 항상 같은 폴백 색 번호(1..8)를 준다(FNV-1a). */
export function fallbackIndex(id: string) {
  let hash = 0x811c9dc5;
  for (let i = 0; i < id.length; i++) {
    hash ^= id.charCodeAt(i);
    hash = Math.imul(hash, 0x01000193);
  }
  return ((hash >>> 0) % FALLBACK_PALETTE_SIZE) + 1;
}

const HEX = /^#[0-9a-f]{6}$/i;

/** 기업 원의 채움색. brandColor가 올바른 #RRGGBB가 아니면 폴백 팔레트. */
export function companyFill(id: string, brandColor: string | null | undefined) {
  if (brandColor && HEX.test(brandColor)) return brandColor.toUpperCase();
  return cssVar(`graph-company-fallback-${fallbackIndex(id)}`) || "#2F6F9F";
}

/** 폴백 팔레트 CSS 변수(목록 표지처럼 DOM에서 쓸 때). Tailwind는 클래스로 쓰지 않은 --color-* 변수를 내보내지 않으므로
 *  항상 존재하는 --zoop-* 원본 변수를 쓴다. */
export function companyFillVar(id: string, brandColor: string | null | undefined) {
  if (brandColor && HEX.test(brandColor)) return brandColor;
  return `var(--zoop-graph-company-fallback-${fallbackIndex(id)})`;
}

function luminance(hex: string) {
  const channel = (i: number) => {
    const c = parseInt(hex.slice(i, i + 2), 16) / 255;
    return c <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4;
  };
  return 0.2126 * channel(1) + 0.7152 * channel(3) + 0.0722 * channel(5);
}

export function contrastRatio(a: string, b: string) {
  if (!HEX.test(a) || !HEX.test(b)) return 21;
  const [hi, lo] = [luminance(a), luminance(b)].sort((x, y) => y - x) as [number, number];
  return (hi + 0.05) / (lo + 0.05);
}

const LIGHT_GLYPH = "#FFFFFF";
const DARK_GLYPH = "#0E1110";

/** 채움색 위에 올릴 글리프 색: 흰색과 거의 검정 중 대비가 큰 쪽. */
export function glyphColor(fill: string) {
  return contrastRatio(fill, LIGHT_GLYPH) >= contrastRatio(fill, DARK_GLYPH) ? LIGHT_GLYPH : DARK_GLYPH;
}

/** 원 이름 첫 글자: 한글은 첫 음절, 로마자는 단어 첫 글자 두 개까지(예: "Taiwan Semiconductor" → TS). */
export function initials(name: string) {
  const words = name.trim().split(/\s+/).filter(Boolean);
  const first = words[0] ?? "?";
  if (/^[A-Za-z]/.test(first)) {
    return words
      .filter((w) => /^[A-Za-z0-9]/.test(w))
      .slice(0, 2)
      .map((w) => w[0]!.toUpperCase())
      .join("");
  }
  return Array.from(first)[0] ?? "?";
}

const GLYPH_PX = 128;
const glyphCache = new Map<string, Promise<string | null>>();

/** SVG에 크기가 없으면 캔버스가 크기를 알 수 없으므로 viewBox로 폭·높이를 채워 blob URL로 다시 싣는다. */
async function loadLogo(url: string): Promise<HTMLImageElement> {
  const text = await fetch(url).then((r) => {
    if (!r.ok) throw new Error(`logo ${r.status}`);
    return r.text();
  });
  const doc = new DOMParser().parseFromString(text, "image/svg+xml");
  const svg = doc.documentElement;
  if (svg.nodeName !== "svg") throw new Error("not svg");
  const box = (svg.getAttribute("viewBox") ?? "").split(/[\s,]+/).map(Number);
  const [w, h] = box.length === 4 && box[2]! > 0 && box[3]! > 0 ? [box[2]!, box[3]!] : [24, 24];
  const scale = 256 / Math.max(w, h);
  svg.setAttribute("width", String(Math.round(w * scale)));
  svg.setAttribute("height", String(Math.round(h * scale)));
  const blobUrl = URL.createObjectURL(new Blob([new XMLSerializer().serializeToString(svg)], { type: "image/svg+xml" }));
  try {
    const img = new Image();
    img.src = blobUrl;
    await img.decode();
    return img;
  } finally {
    URL.revokeObjectURL(blobUrl);
  }
}

/** 로고를 한 가지 색 실루엣으로 칠해 투명 PNG로 만든다(원 폭의 56% 안에 맞춤). */
async function logoGlyph(url: string, color: string) {
  const img = await loadLogo(url);
  const canvas = document.createElement("canvas");
  canvas.width = canvas.height = GLYPH_PX;
  const ctx = canvas.getContext("2d")!;
  const box = GLYPH_PX * 0.56;
  const ratio = img.naturalWidth / Math.max(1, img.naturalHeight);
  const [w, h] = ratio >= 1 ? [box, box / ratio] : [box * ratio, box];
  ctx.drawImage(img, (GLYPH_PX - w) / 2, (GLYPH_PX - h) / 2, w, h);
  ctx.globalCompositeOperation = "source-in";
  ctx.fillStyle = color;
  ctx.fillRect(0, 0, GLYPH_PX, GLYPH_PX);
  return canvas.toDataURL("image/png");
}

function initialsGlyph(text: string, color: string) {
  const canvas = document.createElement("canvas");
  canvas.width = canvas.height = GLYPH_PX;
  const ctx = canvas.getContext("2d")!;
  const family = getComputedStyle(document.documentElement).getPropertyValue("--font-sans").trim() || "sans-serif";
  ctx.font = `700 ${text.length > 1 ? 48 : 56}px ${family}`;
  ctx.fillStyle = color;
  ctx.textAlign = "center";
  ctx.textBaseline = "middle";
  ctx.fillText(text, GLYPH_PX / 2, GLYPH_PX / 2 + 3);
  return canvas.toDataURL("image/png");
}

/**
 * 기업 원 안에 들어갈 글리프 이미지(data URL). 로고를 못 불러오면 이니셜로 대신한다.
 * 같은 (로고, 글자, 색)은 한 번만 만든다.
 */
export function companyGlyph(opts: { logoUrl: string | null | undefined; name: string; color: string }): Promise<string | null> {
  const text = initials(opts.name);
  const key = `${opts.logoUrl ?? ""}|${text}|${opts.color}`;
  let pending = glyphCache.get(key);
  if (!pending) {
    pending = (opts.logoUrl ? logoGlyph(opts.logoUrl, opts.color) : Promise.reject(new Error("no logo")))
      .catch(() => initialsGlyph(text, opts.color))
      .catch(() => null);
    glyphCache.set(key, pending);
  }
  return pending;
}

/** lucide "zap"(번개) 아이콘을 사건 노드용 SVG data URL로. 사건 = 번개로 앱 전체에서 통일한다. */
export function issueGlyph(color: string) {
  const svg = `<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="${color}" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M15.914 4a1.5 1.5 0 00-2.474-1.561l-9 9A1.5 1.5 0 005.5 14h4.002a.5.5 0 01.471.666L8.086 20a1.5 1.5 0 002.475 1.56l9-9A1.5 1.5 0 0018.5 10h-3.997a.5.5 0 01-.472-.667z"/></svg>`;
  return `data:image/svg+xml;utf8,${encodeURIComponent(svg)}`;
}

const numberCache = new Map<string, string>();

function fontFamily() {
  return getComputedStyle(document.documentElement).getPropertyValue("--font-sans").trim() || "sans-serif";
}

/** 묶음 노드 안의 개수 글리프(투명 배경 + 숫자). 문서 글꼴(SUIT)로 그리려고 SVG 대신 캔버스를 쓴다. */
export function countGlyph(count: number, color: string) {
  const key = `count|${count}|${color}`;
  let url = numberCache.get(key);
  if (!url) {
    const canvas = document.createElement("canvas");
    canvas.width = canvas.height = GLYPH_PX;
    const ctx = canvas.getContext("2d")!;
    const text = String(count);
    ctx.font = `700 ${text.length > 2 ? 44 : 56}px ${fontFamily()}`;
    ctx.fillStyle = color;
    ctx.textAlign = "center";
    ctx.textBaseline = "middle";
    ctx.fillText(text, GLYPH_PX / 2, GLYPH_PX / 2 + 3);
    url = canvas.toDataURL("image/png");
    numberCache.set(key, url);
  }
  return url;
}

/** 근거 수 배지 크기 비율(가로/세로). 세 자리 이상이면 알약 모양으로 넓힌다. */
export function badgeAspect(count: number) {
  return String(count).length >= 3 ? 1.6 : String(count).length === 2 ? 1.25 : 1;
}

/**
 * 사건 노드 오른쪽 위 근거 수 배지: 채운 원(알약) + 숫자, 바깥에 바탕색 테두리로 노드와 떼어 놓는다.
 * 숫자 색과 채움색은 호출부가 대비 4.5:1 이상인 토큰 쌍으로 준다.
 */
export function evidenceBadge(count: number, colors: { fill: string; text: string; ring: string }) {
  const key = `badge|${count}|${colors.fill}|${colors.text}|${colors.ring}`;
  let url = numberCache.get(key);
  if (!url) {
    const h = GLYPH_PX;
    const w = Math.round(h * badgeAspect(count));
    const canvas = document.createElement("canvas");
    canvas.width = w;
    canvas.height = h;
    const ctx = canvas.getContext("2d")!;
    const pill = (inset: number) => {
      const r = h / 2 - inset;
      ctx.beginPath();
      ctx.arc(h / 2, h / 2, r, Math.PI / 2, (Math.PI * 3) / 2);
      ctx.arc(w - h / 2, h / 2, r, (Math.PI * 3) / 2, Math.PI / 2);
      ctx.closePath();
    };
    ctx.fillStyle = colors.ring;
    pill(0);
    ctx.fill();
    ctx.fillStyle = colors.fill;
    pill(h * 0.1);
    ctx.fill();
    ctx.font = `700 ${Math.round(h * 0.56)}px ${fontFamily()}`;
    ctx.fillStyle = colors.text;
    ctx.textAlign = "center";
    ctx.textBaseline = "middle";
    ctx.fillText(String(count), w / 2, h / 2 + h * 0.03);
    url = canvas.toDataURL("image/png");
    numberCache.set(key, url);
  }
  return url;
}
