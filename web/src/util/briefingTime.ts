import { formatKst } from './format';

/** 브리핑 시각 '2026-09-17 07:41 KST'. 없거나 읽을 수 없으면 '확인되지 않음' */
export function briefingTime(value: string | null) {
  const text = formatKst(value);
  return text === '미제공' ? '확인되지 않음' : text;
}

/** API may serialize the same cutoff in UTC or with a numeric offset. */
export function sameBriefingInstant(
  left: string | null | undefined,
  right: string | null | undefined,
): boolean {
  if (typeof left !== 'string' || typeof right !== 'string') return false;
  const a = Date.parse(left),
    b = Date.parse(right);
  return Number.isFinite(a) && Number.isFinite(b) && a === b;
}
