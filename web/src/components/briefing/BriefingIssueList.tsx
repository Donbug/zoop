// D-BRF-01 / 02
// TODO: 핵심 이슈·선정 이유·근거·회차 지도·피드백을 연결한다.
export default function BriefingIssueList() {
  return (
    <section
      className="briefing-section"
      aria-labelledby="briefing-issues-title"
    >
      <h3 id="briefing-issues-title">핵심 이슈</h3>
      <p className="briefing-empty">
        이 회차의 핵심 이슈를 준비하고 있어요. 데이터가 연결되면 선정 이유와
        근거 문서, 관계 그래프를 함께 확인할 수 있습니다.
      </p>
    </section>
  );
}
