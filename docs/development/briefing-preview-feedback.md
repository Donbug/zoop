# 브리핑 미리보기 사용자 평가 (D-BRF-01/02)

현재 로컬에서 생성 결과를 확인하는 사람이 회차 전체와 개별 이슈에
`도움이 됐어요 / 도움이 안 됐어요`를 남기는 기능이다. 부정 평가에는
선택 사유를 200자까지 저장한다. 같은 버튼은 취소(`none`), 다른 버튼은
평가 변경이며 새로고침하면 저장된 값을 복원한다.

## 적용 범위

- `VITE_BRIEFING_PREVIEW_FEEDBACK=true`로 실행한 미리보기에서만 켠다.
  기본값은 꺼짐이다. 유효한 `issueIntelligence` 결과가 있어야 한다.
- 운영 회원용 `/api/v1/feedback`이나 `targetVersion=graphVersion` 계약을
  변경하지 않는다. 회원을 임의로 만들거나 회원 인증을 우회하지 않는다.
- 미리보기 API는 `/api/local/briefing-feedback`이다. 로컬 브라우저 평가이며
  로그인 회원 평가·관리자 통계·여러 기기 동기화가 아니다.
- 같은 브라우저에서도 회차·생성 결과 버전·이슈가 다르면 별개 평가다.
  쿠키를 지우거나 다른 호스트 이름으로 접속하면 기존 평가자의 신원을
  복원할 수 없다. 저장 파일 자체는 삭제되지 않는다.

## 연결 방법

`scripts/briefing_preview_feedback.py`의 `PreviewFeedbackStore`에 저장 경로와
현재 서비스할 발행 응답 목록을 전달한다. 원본 JSON·발행 DB는 수정하지 않는다.
평가 SQLite 파일은 Git 밖의 로컬 전용 폴더에 보관한다.

```python
store = PreviewFeedbackStore(private_directory / 'feedback.sqlite3', responses)

class Handler(PreviewFeedbackHttp, BaseHTTPRequestHandler):
    feedback_store = store
    feedback_origins = frozenset({'http://127.0.0.1:13188'})

    def do_GET(self):
        if self.feedback_request():
            return
        # 기존 브리핑 읽기 경로 처리

    def do_PUT(self):
        if not self.feedback_request():
            self.send_error(404)
```

서버는 `127.0.0.1`에만 바인딩한다. Vite의 기존 `ZOOP_DEV_API_TARGET`으로
같은 Origin의 `/api`를 전달한다. 임의의 CORS 허용을 추가하지 않는다.

GET은 `roundId`, `resultVersion`, `feature`, `targetId`를 받는다.
PUT은 같은 식별자에 `value`와 `reason`을 추가한다. 서버가 제공한
HttpOnly/SameSite 쿠키 및 CSRF 토큰, 허용된 Origin이 필요하다.
서버는 현재 판본과 실제 포함된 이슈인지 확인한다. 없는 대상은 404,
구버전은 409, 잘못된 입력은 422다. 화면은 실패하면 마지막 확정값을
유지하고 같은 요청을 재시도하거나 저장 상태를 다시 읽을 수 있다.

최초 카드들의 GET은 순서대로 실행해 브라우저 식별 쿠키가 여러 개 만들어지는
경쟁을 방지한다. PUT은 토글 명령이 아니라 최종 상태를 upsert하므로
응답 유실 후 같은 요청을 재전송해도 반대로 바뀌지 않는다. 취소도 행을 삭제하지 않는다.

## 확인

- Python 저장·HTTP 테스트: 저장소 재개, 판본/회차/이슈/브라우저 격리,
  CSRF/Origin, 취소와 재전송 검증.
- UI 테스트: 사유 복원, 변경·취소, 실패 후 동일 요청 재시도,
  판본 전환 중 늦은 응답 무시, 첫 GET 순서 보장.
- 실제 로컬 화면에서 저장 후 새로고침 복원 및 취소를 확인한다.
- 운영 회원 DB·공개 API에 연결하려면 기존 feedback 계약의 서버 구현과
  발행본 식별을 별도 연결해야 한다. 이 미리보기 저장을 운영 기능 완료로 취급하지 않는다.
