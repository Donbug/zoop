# A-ADM-03 · 그래프 관제·검수

[전체 목록](index.md) · [검사 결과](warnings.md)

- 라우트: `/admin/pipeline`
- 화면계획서 캡처 쪽수: **65**
- 원본: [docs/screen-plan/captures/slide-index.json:65 (slide-page)](../../../docs/screen-plan/captures/slide-index.json)

| 기능 | 목표 API | 경로 | 우선순위 |
| --- | --- | --- | --- |
| [FS058](feature-FS058.md) · [FS059](feature-FS059.md) · [FS063](feature-FS063.md) · [FS067-01](feature-FS067-01.md) | [getPipelineOverview](../../api/out/zoop-api-spec.md#getpipelineoverview) | GET /api/v1/admin/pipeline/overview | P1 |
| [FS067-01](feature-FS067-01.md) · [FS067-02](feature-FS067-02.md) | [listAnalysisCandidates](../../api/out/zoop-api-spec.md#listanalysiscandidates) | GET /api/v1/admin/pipeline/candidates | P1 |
| [FS067-01](feature-FS067-01.md) · [FS067-02](feature-FS067-02.md) | [getAnalysisCandidate](../../api/out/zoop-api-spec.md#getanalysiscandidate) | GET /api/v1/admin/pipeline/candidates/{candidate_id} | P1 |
| [FS059](feature-FS059.md) · [FS067-02](feature-FS067-02.md) | [decideAnalysisCandidate](../../api/out/zoop-api-spec.md#decideanalysiscandidate) | POST /api/v1/admin/pipeline/candidates/{candidate_id}/decision | P1 |
| [FS059](feature-FS059.md) · [FS067-01](feature-FS067-01.md) | [listPublicationRules](../../api/out/zoop-api-spec.md#listpublicationrules) | GET /api/v1/admin/pipeline/rules | P1 |
| [FS059](feature-FS059.md) · [FS067-02](feature-FS067-02.md) | [setPublicationRule](../../api/out/zoop-api-spec.md#setpublicationrule) | PUT /api/v1/admin/pipeline/rules/{rule_id} | P1 |
| [FS059](feature-FS059.md) · [FS067-01](feature-FS067-01.md) | [listGraphVersions](../../api/out/zoop-api-spec.md#listgraphversions) | GET /api/v1/admin/graph/versions | P1 |
| [FS059](feature-FS059.md) · [FS067-02](feature-FS067-02.md) | [publishGraphVersion](../../api/out/zoop-api-spec.md#publishgraphversion) | POST /api/v1/admin/graph/versions | P1 |
| [FS059](feature-FS059.md) · [FS067-02](feature-FS067-02.md) | [activateGraphVersion](../../api/out/zoop-api-spec.md#activategraphversion) | POST /api/v1/admin/graph/versions/{version_id}/activate | P1 |
| [FS058](feature-FS058.md) · [FS067-01](feature-FS067-01.md) | [listAnalysisJobs](../../api/out/zoop-api-spec.md#listanalysisjobs) | GET /api/v1/admin/jobs | P1 |
| [FS058](feature-FS058.md) · [FS059](feature-FS059.md) · [FS063](feature-FS063.md) · [FS064](feature-FS064.md) | [createAnalysisJob](../../api/out/zoop-api-spec.md#createanalysisjob) | POST /api/v1/admin/jobs | P1 |
| [FS067-01](feature-FS067-01.md) | [getAnalysisJob](../../api/out/zoop-api-spec.md#getanalysisjob) | GET /api/v1/admin/jobs/{job_id} | P1 |
| [FS067-03](feature-FS067-03.md) | [retryAnalysisJob](../../api/out/zoop-api-spec.md#retryanalysisjob) | POST /api/v1/admin/jobs/{job_id}/retry | P1 |
| [FS067-03](feature-FS067-03.md) | [cancelAnalysisJob](../../api/out/zoop-api-spec.md#cancelanalysisjob) | POST /api/v1/admin/jobs/{job_id}/cancel | P1 |

공통 품질: [NFS001](feature-NFS001.md) · [NFS002](feature-NFS002.md) · [NFS004](feature-NFS004.md) · [NFS008](feature-NFS008.md) · [NFS012](feature-NFS012.md) · [NFS003](feature-NFS003.md) · [NFS009](feature-NFS009.md)
