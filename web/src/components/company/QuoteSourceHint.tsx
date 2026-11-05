import PanelDisclosure from '@/components/graph/PanelDisclosure';
import type { Source } from '@/types/company/detail';

const derivedNote: Record<string, string> = {
  marketCap: '시가총액은 현재가 × 발행주식수로 계산했어요.',
  previousClose: '전일 종가는 직전 거래일 일봉 종가예요.',
  fiftyTwoWeekHigh: '52주 고저는 최근 1년 일봉으로 계산했어요.',
};

/** D-COM-01 D10: prototype company-quote source hint, using supplied fields only. */
export default function QuoteSourceHint({
  source,
  derived = [],
}: {
  source: Source;
  derived?: string[];
}) {
  let href: string | undefined;
  try {
    const url = new URL(source.url ?? '');
    if (
      ['http:', 'https:'].includes(url.protocol) &&
      !url.username &&
      !url.password
    )
      href = url.href;
  } catch {
    /* A missing or unsafe source has no external link. */
  }
  return (
    <PanelDisclosure
      label={`시세 출처: ${source.name}`}
      trigger={source.name}
      wideTarget
    >
      <p>
        {source.official ? '공식 시세 API' : '공개 자료'} · 종목 기호{' '}
        {source.symbol}
      </p>
      {source.delayNote && <p>{source.delayNote}</p>}
      {derived
        .filter((key, index) => derived.indexOf(key) === index)
        .map((key) =>
          derivedNote[key] ? <p key={key}>{derivedNote[key]}</p> : null,
        )}
      {href && (
        <a
          href={href}
          target="_blank"
          rel="noopener noreferrer"
          className="inline-flex min-h-10 items-center underline underline-offset-2"
        >
          출처에서 확인하기
        </a>
      )}
    </PanelDisclosure>
  );
}
