// 화면 표시용 숫자·시각 서식. 서로 다른 통화는 환율로 바꾸지 않는다.

export function formatQuantity(quantity: number) {
  return `${quantity.toLocaleString('ko-KR')}주`;
}

/** 자산 비중(0..1). 계산할 수 없으면 그대로 알린다. */
export function formatWeight(weight: number | null) {
  if (weight === null) return '비중 계산 불가';
  return `비중 ${(weight * 100).toLocaleString('ko-KR', {
    maximumFractionDigits: 1,
  })}%`;
}
