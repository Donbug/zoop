/**
 * D-BRF-04: 회차 기준 지도가 실패한 것이 아니라 제공되지 않는 상태(미지원·제공 중단·미발행 등).
 * 다시 요청해도 같은 결과이므로 화면은 조회 실패·다시 시도 대신 제공하지 않는다는 안내를 보인다.
 */
export class RoundGraphUnavailableError extends Error {
  constructor(message: string) {
    super(message);
    this.name = 'RoundGraphUnavailableError';
  }
}
