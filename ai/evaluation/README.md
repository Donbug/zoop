# ai/evaluation: 기록된 출력의 결정적 채점 하네스

이미 기록된 그래프 구성·검색·답변 출력과 trace를, 따로 작성한 gold와 비교해 채점한다. 표준 라이브러리만 쓰며(Python 3.12 이상) 모델·네트워크·그래프 DB를 호출하지 않는다. 지표 정의, 데이터 분리, gold 검수, baseline과 측정 계획, 승인 경계는 [`docs/design/ai-benchmark.md`](../../docs/design/ai-benchmark.md)에 있고 여기서 반복하지 않는다.

## 명령

저장소 루트 기준이다.

```bash
cd ai/evaluation
python3 -B -m unittest discover -s tests          # 시험
python3 -B scripts/smoke.py                       # 일회성 smoke: 진입점, 전 명령, 거부 경로
python3 -B -m zoop_eval validate                  # corpus·gold 무결성과 dev/test 분리
python3 -B -m zoop_eval controls --out-dir fixtures/controls   # authored control 재생성
python3 -B -m zoop_eval score fixtures/controls/degraded-dev.run.json --format text
python3 -B -m zoop_eval score RUN.json [--format json|text] [--out score.json]
python3 -B -m zoop_eval compare RUN_A.json RUN_B.json [--format text]
```

종료 코드는 성공 0, 입력 거부 2이며 거부 시 stdout에 `{"ok": false, "error": {"code", "message"}}`를 낸다.

## 구성

| 경로 | 내용 |
|---|---|
| `corpus/zoop-bench-v1/` | 허구의 합성 corpus. `corpus.json`·`tasks.json`은 시스템에 보이는 입력, `gold.json`은 시스템에 숨기는 정답 |
| `zoop_eval/` | 검증, 채점, 비교, 보고 모듈과 CLI |
| `fixtures/controls/` | authored control 3개(`oracle-dev`, `oracle-test`, `degraded-dev`) |
| `tests/`, `scripts/smoke.py` | 시험과 smoke |

run 파일(`zoop-bench-run-1`) 형식은 위 설계 문서의 “입력 계약”을 따른다. 미래의 모델·도구 adapter는 이 파일만 만들면 된다.

## 한계

- 측정한 시스템이 없다. 저장소에 검색기·채팅·그래프 DB 실행 코드가 없고, 현재 점수는 모두 채점기 점검용 authored control이다. control은 `real_measured` 결과와 같은 표에 올리거나 순위를 매기지 않는다(`compare`가 거부한다).
- gold는 단일 작성자 초안이며 합의를 거치지 않았고(`adjudicated=false`) 규모가 작아 비율이 거칠다. 영어 합성 문장이라 한국어 표현은 검증하지 않는다.
- 자유 서술 품질과 인용의 의미적 뒷받침은 자동 지표가 없고 사람 또는 모델 평가가 필요하다.
- 실제 모델 호출, 외부·경쟁 서비스 질의, 그래프 DB 설치, 새 의존성, test split 사용은 사용자 승인 전에는 하지 않는다. WBS는 변경하지 않는다.
- 루트 `Makefile`과 CI에는 아직 연결하지 않았다.
