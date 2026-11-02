# 챗봇 실데이터 readiness gate

이 gate는 `first47` 같은 승인된 데이터셋이 PostgreSQL과 serving artifact root에 같은 상태로 설치됐는지 확인한다.
모델을 호출하거나 그래프를 활성화하지 않으며, 회원·질문·답변·인용문·문서 본문·자격 증명을 읽거나 보고서에 남기지 않는다.

## 기대 manifest

운영자는 실제 ID를 확정한 뒤 Git 밖의 승인된 저장소에 다음 닫힌 JSON을 둔다. 첫 native 버전은 이전 nonfixture가
없으므로 `requirePreviousNonFixture=false`로 검사할 수 있다. Q05 기간 비교를 출시하기 전에는 `true`로 바꿔 두 번째
공개 native 버전까지 요구한다.

```json
{
  "schemaVersion": "zoop-chat-data-expectation-1",
  "datasetId": "first47",
  "activeGraphVersionId": "gv-<actual-id>",
  "requirePreviousNonFixture": false,
  "expectedArtifactStoreId": "dev-first47-serving",
  "minimumCounts": {
    "companies": 47,
    "availableArticles": 1,
    "articleVersions": 1,
    "verifiedEvidence": 1,
    "nonFixtureGraphVersions": 1
  },
  "minimumActiveGraphCounts": {
    "issueCount": 1,
    "articleCount": 1
  },
  "requiredCompanyIds": ["<47 approved company ids>"]
}
```

`minimumCounts`는 `companies`, `articles`, `availableArticles`, `articleVersions`, `evidence`, `verifiedEvidence`,
`publishedBriefings`, `nonFixtureGraphVersions` 중 필요한 항목만 쓴다. 그래프 최소값은 `issueCount`, `relationCount`,
`articleCount`이다. 실제 ID를 모르는 placeholder manifest는 실행하지 않는다.

## 실행

같은 DB와 artifact mount를 보는 승인된 운영 컨테이너에서 실행한다. `psql` 출력에는 내용이나 비밀이 없지만 결과 파일은
운영 증거 저장소에 둔다.

```sh
psql "$READ_ONLY_DATABASE_URL" -X -At -v ON_ERROR_STOP=1 \
  -f scripts/chat_data_readiness.sql > /secure/operator/first47-inventory.json

python scripts/chat_data_readiness.py \
  /secure/operator/first47-expectation.json \
  /secure/operator/first47-inventory.json \
  --artifact-root /var/lib/zoop-artifacts \
  --output /secure/operator/first47-readiness.json
```

성공은 exit 0과 `status=passed`, 데이터·버전·파일 불일치는 exit 2, 입력 형식 오류는 exit 64다. gate는 DB에 쓰지
않고 기능 플래그를 켜지 않으며, artifact root의 `.zoop-artifact-store-id`도 기대 manifest와 대조한다.

## 공개 챗봇 데이터 경로 smoke

readiness가 통과한 버전에서 답변 모델을 부르지 않고 챗봇의 `company.read`·`document.search`·
`evidence.resolve` 원천이 같은 버전을 보는지 공개 HTTP로 확인한다. 실제 그래프에 존재하는 회사·그 회사의
문서에 포함된 evidence 한 건을 승인된 저장소의 probe로 고정한다.

```json
{
  "schemaVersion": "zoop-chat-nonfixture-probe-1",
  "graphVersionId": "gv-<actual-id>",
  "companyId": "<actual-company-id>",
  "evidenceId": "<actual-readable-evidence-id>",
  "minimumDocuments": 1
}
```

```sh
python scripts/chat_nonfixture_smoke.py /secure/operator/first47-probe.json \
  --base-url "https://dev-api.example" \
  --output /secure/operator/first47-public-chat-data-smoke.json
```

스크립트는 redirect와 외부 HTTP를 거절하고 응답 본문·인용문을 결과에 남기지 않는다. 결과에는 버전·ID·개수와
실패 코드만 남는다. 이 smoke는 데이터 읽기 경로이며 실제 Luna/Jev 품질·비용·지연 검증은 `chat-live-spike.md`의
별도 승인 gate로 실행한다.
