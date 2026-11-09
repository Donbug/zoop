# 자동 브리핑의 일반 뉴스·기업 발표 연결

`scripts/briefing_news_intake.py`는 최신 pipeline의 `news_archives.py`·`news_sources.py`를 재사용한다. 과거 PoC·Exa 검색을 호출하지 않는다. 기존 정부 자료·삼성 뉴스룸 경로를 보존한 채, 별도로 승인한 일반 뉴스·기업 발표를 **같은 회차 후보 풀**에 넣는다.

```text
정부 자료 + 승인된 기업 발표·일반 뉴스
 → 실제 GET 원문·발표 정밀도·수집 시각 보존
 → 기존 native HTTP collection / ingestion
 → 전체 공통 기업 카탈로그로 입력 준비 순서 결정
 → 기존 native 사건 추출·기업 관계·독립 검증
 → 이슈 선정·공통 분석·공통/개인화 배달
```

수집은 회원마다 반복하지 않는다. 개인화는 기존 로그인·허용 회원·회차 마감 당시 설정을 사용한다. 이 변경은 회원 허용 목록, 설정, 모델 한도, 일정, 이미 발행한 원문이나 평가를 수정하지 않는다. 문서에 회사 이름이 있다는 것만으로 사업 관계나 긍부정이 확정되지 않는다. 품질 보류 후 다음 미전송 후보를 검토하는 기존 처리도 유지한다.

## 출처 등록과 실행

수집 준비의 기업명 정책은 `briefing-company-literal-v2`다. 기존 카탈로그의 정확한 ID에 한해서 애플·현대차 같은 한글 표기를 native 입력 사본에 추가한다. 두 글자 한글 이름·별명도 고유하고 단어/조사 경계가 맞으면 검토하며, 짧은 영문 약어는 실제 KT issuer 이외에는 허용하지 않는다. 네이버파이낸셜/네이버, 카카오톡/카카오, KT&G/KT, 현대차그룹/현대차 구분을 유지한다. 원래 카탈로그 파일·DB 별칭·과거 분석은 수정하지 않으며 회사의 역할·영향을 확정하는 규칙으로 쓰지 않는다.

worker 환경변수 `BRIEFING_NEWS_SOURCE_REGISTRY`에 비공개 0600 파일의 절대 경로를 지정한다. 예: `/mnt/zoop-artifacts/briefing-news-sources-v1.json`. 실제 출처 승인 문서·현재 grant는 운영자가 확인한 값이어야 한다. URL이나 private collector의 시험용 기본값을 공개·모델 권한으로 자동 전환하지 않는다.

등록 형식 예시는 **비활성·권한 미확인**이다. 이것을 그대로 배포해도 수집이나 AI 전송을 시작하지 않는다.

```json
{
  "schemaVersion": "briefing-news-sources-v1",
  "revision": "review-required-v1",
  "sources": [{
    "sourceId": "etnews-ai",
    "enabled": false,
    "authorizationRef": "REPLACE_WITH_REVIEWED_SOURCE_AUTHORITY",
    "nativeProcessing": {
      "profile": "briefing-native-v2-standard",
      "recipients": [],
      "authorizationRef": "REPLACE_WITH_NATIVE_PROVIDER_AUTHORIZATION"
    },
    "maxListingPages": 2,
    "maxArticleAttempts": 6,
    "maxDocuments": 3,
    "grant": {
      "grantId": "REPLACE_WITH_CURRENT_OWNED_GRANT",
      "revision": "REPLACE_WITH_CURRENT_REVISION",
      "sourceId": "etnews-ai",
      "enabled": false,
      "rights": "unknown",
      "allowedOperations": [],
      "recipients": [],
      "purposes": [],
      "evidence": [],
      "expiresAt": null
    }
  }]
}
```

일반 뉴스는 최신 증권·IT RSS의 `hankyung-feed`, 과거 일자별 sitemap의 `hankyung-daily`, `etnews-ai`, `fnnews-sitemaps`, 기업 발표는 `nvidia-newsroom`, `amd-newsroom`, `naver-press`, `apple-newsroom` 및 기존 configured adapter를 사용할 수 있다. **구현된 adapter가 있다는 사실은 실시간 접근 성공·본문 구조·사용 권한 확인을 뜻하지 않는다.** 차단 등록된 출처·PDF 전용 경로는 이 HTML 경로로 우회하지 않는다. 기존 삼성 전용 경로는 자체 작성자·이용 안내를 확인하는 원래 설정으로 계속 사용한다.

활성 출처는 현재 `enabled/rights=known` grant의 `read/store/quote-display/model-send`, 근거, 만료를 확인한다. 공통 전망·검증의 serving grant에는 기존 S1 계약대로 `openai`와 `briefing-outlook`·`semantic-verification` 목적이 필요하다. `nativeProcessing`에는 고정 profile과 `openai`·`typesafe-native` 수신자 승인이 별도로 있어야 한다. public serving 권한만으로 다른 검증 서비스 전송까지 허용하지 않는다. native S2/S3는 이 승인 범위에서 원문/영수증에 묶인 별도 prospective grant를 만든다. 기존 grant나 다른 담당자 파일은 덮어쓰지 않으며 같은 ID의 값이 다르면 중단한다. 출처 등록 변경은 다음 수집부터 적용하며 과거 획득본은 그대로 보존한다. 공개 조회의 철회는 실제 serving grant 소유 파일에서 처리한다. 수집 설정을 끄는 것만으로 이미 공개된 원문을 삭제하지 않는다.

## 마감 시각과 재사용

- RSS·sitemap의 날짜는 요청 순서 힌트다. 실제 본문의 원래 발표 메타데이터와 실제 GET 시각을 사용한다.
- 정확한 발표 시각은 `(windowFrom, windowTo]` 안에 있어야 한다. 실제 GET 시각도 이 범위여야 한다. 뒤늦게 수집한 기사를 과거 08:30 입력으로 위장하지 않는다.
- 날짜만 제공하는 출처는 날짜를 자정으로 바꾸지 않는다. 기존 native 계약의 `first_observed`로 취급하고 정확한 발표 시각·회차 시작 이후 새 발표라는 판단은 유보한다. 새 정보·재보도 검증을 생략하지 않는다.
- 원문 GET 바이트 하나로 메타데이터와 native evidence를 함께 만든다. collection/ingestion을 위해 원문을 다시 가져오지 않는다.
- 같은 회차의 완료 결과는 registry·회차·파일·원문 SHA를 대조한 뒤 네트워크나 AI 없이 재사용한다. 중간에 끊겨 완료 묶음이 없는 획득은 자동 재전송하지 않는다. 기존 미응답 AI도 재전송하지 않는다.
- 원문 전문·키·회원 식별자는 public 상태 로그에 넣지 않는다. 원문과 권한 파일은 기존 private native 저장소에 보관한다.

## 한도와 수집 범위

새 자동화는 `briefing-news-refill-v1`을 사용한다. 기본 목표는 기업 카탈로그와 연결되는 원문 20개이며 **새 사건 20개 또는 핵심 이슈 3개를 보장하는 값이 아니다**. 기존 정부·삼성 자료도 같은 후보 풀에 포함한다. 목표에 못 미치면 새 수집 묶음을 더 받고, 이후 검증·선정에서 풀이 소진돼도 마감·호출 예산이 남으면 다시 보충한다. 동일 사건·근거·재보도·기업 관계 검증은 계속 적용한다.

뉴스 출처들이 회차 전체에서 공유하는 기본 한도는 6묶음·요청 120회·네트워크/호스트 대기 300초·응답 100MB다. 마감 360초 전에는 새 수집을 시작하지 않아 후속 native 검증·선정 시간을 남긴다. 매 묶음에 출처별 목록 1페이지와 기사 최대 8개를 처리하고, 다음 묶음은 시작 출처를 바꾼다. 출처별 등록 한도도 누적 적용한다. 정부·삼성 경로는 원래 한도를 유지한다. 전체 시장의 모든 뉴스를 수집한다는 의미가 아니다.

동일 회차의 이미 방문한 기사 URL은 다시 요청하지 않는다. 남은 목록 페이지·새 URL을 우선 검토하고, 목록과 대기열이 모두 소진되면 등록된 최초 피드를 최대 1회만 새로 확인한다. 같은 본문 SHA는 원문 획득본을 보존하되 후보에 중복 추가하지 않는다. 페이지 안 URL 중복도 제거한다. 보존 대기열은 출처별 기사 240개·목록 64개이며 잘린 개수는 별도로 기록한다. robots·401/403/429·네트워크 제한은 기록하고 그 출처를 뒤 묶음에서도 자동 반복하지 않는다. 다른 출처는 공유 예산 안에서 계속 확인한다.

현재 v1 registry의 페이지 3·기사 시도 24·문서 8 상한과 실제 설정값은 그대로 유효하다. 확대 설정은 **새 `briefing-news-sources-v2` 리비전**으로 준비한다. v2의 출처별 최대치는 페이지 8·기사 시도 80·문서 30, 출처 개수는 최대 8개다. 코드가 운영 파일을 덮어쓰거나 새 출처를 자동 활성화하지 않는다.

다음 명령은 운영 파일과 별도의 비공개 0600 설정만 생성한다. 기본 확대값은 출처별 페이지 5·기사 시도 60·문서 20이다. `--additional-sources`는 선택 사항이며, 위 형식의 완전한 source 항목 배열을 담은 별도 0600 JSON이다. 기존 grant·수신자·enabled는 보존하고, 활성 출처의 권한이 미확인이면 거부한다. 출력 경로는 Git checkout 밖이어야 한다.

```sh
python3 scripts/prepare_briefing_news_registry.py \
  --current /private/briefing/news-sources-v1.json \
  --output /private/briefing/news-sources-v2.json \
  --revision reviewed-expanded-v2 \
  --additional-sources /private/briefing/reviewed-additional-sources.json
```

생성한 설정을 확인한 뒤 별도 배포 단계에서 `BRIEFING_NEWS_SOURCE_REGISTRY`를 새 파일로 지정한다. 같은 회차 도중 registry·정책 SHA를 바꾸면 중단한다. 실제 등록 출처가 하나라면 이 도구만으로 여러 언론사를 수집하게 되지는 않는다. 추가 출처는 기존 adapter 지원과 현재 source/native 권한을 갖춘 항목을 등록해야 한다.

새 획득은 `native/<round>/news-sources-refill-v1/pass-NN/` 아래에 원문 응답·수집 시각·SHA, 실제 collection/ingestion 결과, `state/result/aggregate/commit.json`을 추가한다. 이전 묶음을 덮어쓰지 않는다. 완료 묶음 읽기는 네트워크 0회이며, 명시적 refill만 다음 묶음을 만든다. 미완료 `started.json`은 자동 재전송하지 않고 복구 경계로 남긴다. 검토 과정의 coverage는 `coverage-passes/`에 보존하고 최종 `source-coverage.json`은 한 번 고정한다. 총 후보 수·남은 후보 수·수집 묶음 수·제외 사유·시간/요청/문서 한도 도달을 구분한다. 기존 `news-sources/result.json` 획득본은 원래 reader로 재사용하고 새 형태로 변환하지 않는다.

미설정은 `not_configured`, 미확인 권한은 `rights_prerequisite`, 실행한 범위도 `complete=false`다. 수집이 부족한 것을 시장 전체에 새 소식이 없다고 설명하지 않는다. 이 경로 자체의 AI·회원별 수집 호출은 0회이며, 후속 native·브리핑 요청은 기존 물리 호출·일일 비용 원장을 그대로 사용한다. 다음 정상 문서 검토에 필요한 최소 호출 여유가 없거나 앞선 응답이 미확인 상태라면 보충 수집으로 이를 우회하지 않는다.

OpenDART/SEC의 공식 수집 adapter는 별도 protocol이다. 이 변경은 해당 adapter의 인증·SEC 식별 연락처·공식 문서 변환을 임의로 채우거나 활성화하지 않는다. DART 키, SEC 회사/연락처·CIK와 해당 출처 권한을 준비한 후 별도 연결해야 한다.

## 실패 회차의 화면

공통 조회는 `status=failed`, `publishedAt=null`, 현재 `items=[]`를 유지한다. 새 분석을 완료하지 못한 경우, 현재 제공 가능한 이전 공통 발행본을 별도 `continuity` 참고 영역에서만 보여준다. 이전 원본의 기준 시각·제목·요약·전문 링크와 저장된 다음 확인 조건을 재사용한다. 현재 회차를 새로 발행하거나 과거 전망을 현재 전망·적중 결과로 바꾸지 않는다.

이전 자료는 현재 회차 시작 이전 데이터이면서 실제 발행도 마감 이전이어야 한다. 현재 접근 권한·원본 구조를 다시 검사하며 정정·중단·권한 철회 자료는 복기하지 않는다. 이 참고 영역을 조회해도 DB·AI·개인화 delivery는 생성되지 않는다. 개인화 배달이 없으면 로그인 사용자에게도 **이전 공통 참고 자료이며 내 종목을 새로 분석한 결과가 아님**을 표시한다. 비회원에게 개인화 설정을 요청하지 않는다.

미발행 회차의 예정 시각·schedule metadata는 실제 저장 시각과 현재 `BriefingSchedule`을 사용한다. 이미 발행된 회차의 저장 일정·문안은 바꾸지 않는다.
