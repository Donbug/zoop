import { formatKst } from './format';

/** 브리핑 시각 '2026-09-17 07:41 KST'. 없거나 읽을 수 없으면 '확인되지 않음' */
export function briefingTime(value: string | null) {
  const text = formatKst(value);
  return text === '미제공' ? '확인되지 않음' : text;
}
