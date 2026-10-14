// D-BRF-01 / 02
// TODO: 회차 시각과 지표 관측 시각을 구분하고 정상·지연·사용 불가·실패를 분리한다.
export default function MarketIndicators() {
  return (
    <section
      className="briefing-section"
      aria-labelledby="market-indicators-title"
    >
      <h3 id="market-indicators-title">⌁ 주요 시장 지표</h3>
      <ul className="briefing-indicator-grid">
        {['KOSPI', 'KOSDAQ', '원/달러'].map((name) => (
          <li key={name}>
            <strong>{name}</strong>
            <span>지표 데이터 준비 중</span>
          </li>
        ))}
      </ul>
    </section>
  );
}
