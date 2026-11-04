// 화면 표시용 숫자·시각 서식. 서로 다른 통화는 환율로 바꾸지 않는다.

export function formatQuantity(quantity: number) {
  return `${quantity.toLocaleString('ko-KR')}주`;
}

/** 자산 비중(0..1). 계산할 수 없으면 대시로 표시한다. */
export function formatWeight(weight: number | null) {
  if (weight === null) return '-';
  return `비중 ${(weight * 100).toLocaleString('ko-KR', {
    maximumFractionDigits: 1,
  })}%`;
}

/** 금액. 원화는 '5,430,000원', 그 밖의 통화는 통화 기호 형식('$2,399.00') */
export function formatMoney(amount: number, currency: string) {
  if (currency === 'KRW')
    return `${Math.round(amount).toLocaleString('ko-KR')}원`;
  try {
    return new Intl.NumberFormat('en-US', {
      style: 'currency',
      currency,
    }).format(amount);
  } catch {
    return `${amount.toLocaleString('ko-KR')} ${currency}`;
  }
}

const KST_PARTS = new Intl.DateTimeFormat('en-US', {
  timeZone: 'Asia/Seoul',
  year: 'numeric',
  month: '2-digit',
  day: '2-digit',
  hour: '2-digit',
  minute: '2-digit',
  hourCycle: 'h23',
});

/** ISO 시각을 '2026-10-01 20:33 KST'로. 값이 없거나 읽을 수 없으면 '미제공' */
export function formatKst(iso: string | null) {
  if (!iso) return '미제공';
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return '미제공';
  const part = (type: Intl.DateTimeFormatPartTypes) =>
    KST_PARTS.formatToParts(date).find((item) => item.type === type)?.value;
  return `${part('year')}-${part('month')}-${part('day')} ${part('hour')}:${part('minute')} KST`;
}

/**
 * datetime-local 값(KST로 본 분)을 서버의 분 단위 ISO-8601(UTC)로 바꾼다. 형식 밖이거나 없는 날짜·시각(2월 31일, 24:00 등)이면 null.
 * Date는 없는 날짜를 다음 날로 넘기므로, 바꾼 값을 다시 KST로 읽어 입력과 같은지 확인한다.
 */
export function kstMinuteToIso(value: string) {
  if (!/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}$/.test(value)) return null;
  const at = new Date(`${value}:00+09:00`);
  if (Number.isNaN(at.getTime())) return null;
  const kst = new Date(at.getTime() + 9 * 60 * 60 * 1000).toISOString();
  if (kst.slice(0, 16) !== value) return null;
  return at.toISOString().replace('.000Z', 'Z');
}
