// D-BRF-02
// TODO: 동일 날짜 출근 회차 대비 신규·이어짐·빠짐을 비교한다.
export default function BriefingComparison() {
  return (
    <section
      className="briefing-section"
      aria-labelledby="briefing-comparison-title"
    >
      <h3 id="briefing-comparison-title">아침 대비 변화</h3>
      <p className="briefing-empty">
        출근 브리핑과 비교할 수 있도록 신규·이어짐·빠짐 이슈를 준비하고 있어요.
      </p>
    </section>
  );
}
