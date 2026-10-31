# 뉴스 수집기 컨테이너 런타임 (`zoop-ai-collector`, 2026-10-29)

AWS Fargate의 standalone `RunTask`로 뉴스 **수집**을 돌리기 위한 이미지·명령·상태·종료 계약이다. 인프라(ECR, private S3, CloudWatch Logs, Security Group, task/execution role, Secrets Manager)는 이미 있고, ECS Task Definition과 스케줄은 이 계약을 따라 만든다. 이 문서는 요청받은 일곱 항목을 구현된 그대로 적는다. 모델·분석 단계는 이 이미지의 `run`에 들어 있지 않다.

| # | 항목 | 이 문서 |
|---|---|---|
| 1 | Dockerfile과 build context | §1 |
| 2 | 최종 entry 명령 | §2 |
| 3 | `PRIVATE_CONFIG` / `KOREA_CONFIG` 경로와 공급 | §3 |
| 4 | SQLite writer drain과 일관된 checkpoint | §5 |
| 5 | S3 upload / restore와 manifest | §5, §6 |
| 6 | SIGTERM | §7 |
| 7 | 실행 모드별 Secret 환경변수 이름 | §8 |

## 1. 이미지

- build context는 **`ai/pipeline/`** 하나다. `uv.lock`이 `../worker` 없이 설치된다(worker는 dev 그룹의 테스트 의존성일 뿐이다).
- Python 3.12 slim(trixie) + `uv sync --frozen --no-dev --no-editable --group container`, Node 22(node 이미지의 binary만 복사) + `_defuddle/package-lock.json`의 `npm ci --omit=dev`를 설치된 패키지 안(`.../zoop_ai_pipeline/_defuddle/node_modules`)에 둔다. 비root 사용자 `collector`(uid/gid 10001), init은 `tini`.
- `boto3`는 `pyproject.toml`의 **dependency group `container`**에 고정한다(`boto3==1.43.121`, `uv.lock` 포함). `dev` 그룹도 이 그룹을 포함하므로 CI의 `make pipeline-install`이 실제 S3 전송 시험에 필요한 SDK를 설치한다. 제품의 S3 코드는 `collector_s3.py`에 모여 있다. 자격 증명은 기본 AWS provider chain(ECS task role)으로 공급한다.

```sh
docker build -f ai/pipeline/Dockerfile \
  --build-arg ZOOP_COLLECTOR_IMAGE_REVISION=$(git rev-parse HEAD) \
  ai/pipeline
```

`ZOOP_COLLECTOR_IMAGE_REVISION`은 manifest의 `image.gitCommit`이 된다(커밋된 트리에서 빌드할 때만 이미지 내용과 일치한다). main의 `ai/Dockerfile`(S1 replay worker+service)은 다른 이미지이며 바뀌지 않았다.

## 2. 단일 entry

```
ENTRYPOINT ["/usr/bin/tini", "--", "zoop-ai-collector"]
CMD ["run"]
```

컨테이너의 최종 프로세스 명령은 `zoop-ai-collector run`이다. 이미지의 `ENTRYPOINT`를 유지하는 ECS Task Definition에서는 `command`를 생략하거나 `["run"]`으로 지정한다. `stopTimeout`은 **120**(Fargate 최대)으로 둔다.

| 하위 명령 | 동작 |
|---|---|
| `run` | 설정된 수집 경로마다 worker 프로세스를 하나씩 띄우고 한 controller가 감독한다. 주기·요청·최종 checkpoint를 S3에 올린다. |
| `checkpoint [--timeout S]` | 살아 있는 controller에 checkpoint를 요청하고 끝날 때까지 기다린다. controller가 없으면 거부한다(exit 7). **live DB를 직접 읽지 않는다.** ECS Exec에서 쓴다. |
| `restore [--checkpoint latest\|<seq>-<id>]` | S3 checkpoint를 내려받아 모든 sha256을 확인한 뒤 **빈** 상태 디렉터리에만 설치한다. |
| `status [--remote]` | controller 상태 파일(`control/status.json`)과, `--remote`이면 S3 `latest.json`을 출력한다. |

`zoop-ai-private-news`, `zoop-ai-extract` 등 다른 console script도 이미지에 설치되지만 컨테이너 계약에 들어 있지 않다(§9).

수집 경로는 환경변수로 켠다. 하나 이상 필요하다.

| 경로 | 켜는 변수 | worker가 부르는 코드 | 상태 디렉터리 |
|---|---|---|---|
| `private` | `PRIVATE_CONFIG` | `private_intake.run` (`zoop-private-news-config-1/2`) | `/var/lib/zoop-collector/private` |
| `korea` | `KOREA_CONFIG` | `korea_corpus.run` (`zoop-korea-corpus-1`) | `/var/lib/zoop-collector/korea` |
| `official` | `OFFICIAL_CONFIG` | `official_source_intake.run` (`zoop-official-source-config-1`) | `/var/lib/zoop-collector/official` |

기존 collector 의미는 그대로다: 경로마다 `flock` 단일 writer, 알 수 없는 결과는 재전송하지 않고 unknown으로 남김, receipt·ledger 유지. 첫 실행은 `run`, 상태가 이미 있으면 `resume`을 worker가 고른다(`PLAN.json` 유무). 각 경로는 요청 경계에서만 중단·일시정지한다(`collector_control.py`, §4).

## 3. 컨테이너 경로와 설정 공급

| 경로 | 용도 |
|---|---|
| `/var/lib/zoop-collector/` | state root(task 로컬 디스크, 0700). 아래 `private/`, `korea/`, `official/`이 각 collector의 상태. `controller.lock`, `control/`, `checkpoints/`(임시)는 checkpoint에 들어가지 않는다. |
| `/etc/zoop-collector/private-config.json`, `korea-config.json`, `official-config.json` | 설정(비밀 아님). 시작할 때 받아 sha256을 확인하고 0444로 둔다. |
| `/etc/zoop-collector/korea-rights-evidence.json`, `korea-exclusions.json` | Korea 설정이 가리키는 증거 파일(설정 안의 `rightsEvidence.path`/`exclusionManifest.path`와 같아야 하며 sha256은 설정이 고정한다). |

설정 JSON 자체가 `stateDir`(절대경로)을 담고, collector는 이 값을 기록물(`PLAN.json`, record의 `stateDir`/`recordPath`, Korea의 `inputRoot`)에 박는다. 그래서 **`stateDir`는 반드시 `/var/lib/zoop-collector/<private|korea|official>`** 이어야 하고 `run`이 `state_dir_not_fixed`로 거부한다. 따라서 checkpoint는 같은 경로에만 복원된다.

공급 방식(경로마다 `PRIVATE_`/`KOREA_`/`OFFICIAL_` 접두):

- **S3**: `<P>_CONFIG_S3_URI=s3://bucket/key` + `<P>_CONFIG_SHA256=<64 hex>`(필수). 내려받은 bytes의 sha256이 다르면 아무것도 쓰지 않고 `config_sha256_mismatch`로 끝난다. `<P>_CONFIG`는 `/etc/zoop-collector/` 바로 아래여야 한다.
- **로컬 파일**(`docker run -v ...:ro` 시험용): `<P>_CONFIG`만 지정. `<P>_CONFIG_SHA256`을 주면 검증한다.
- Korea 증거: `KOREA_RIGHTS_EVIDENCE_S3_URI`, `KOREA_EXCLUSIONS_S3_URI`(선택, 없으면 파일이 이미 있어야 함). 설정에 박힌 sha256과 대조한다.

`run`이 거부하는 설정(exit 2, `config_unsupported`): private의 `fallback`(유료 DeepSeek fetch), `predecessor`, `knownUnsent`; official의 `predecessor`. 이들은 호스트 로컬 절대경로의 예산 ledger·set proof·이전 namespace에 의존하며 checkpoint가 이를 담지 않는다.

이미지가 고정하는 비밀 아닌 환경변수: `ZOOP_COLLECTOR_STATE_ROOT=/var/lib/zoop-collector`, `ZOOP_COLLECTOR_CONFIG_DIR=/etc/zoop-collector`, `ZOOP_STATE_DIR=/var/lib/zoop-reserved/application`, `ZOOP_AI_WORKER_STATE_DIR=/var/lib/zoop-reserved/worker`(설치된 패키지는 소스 checkout이 없어 `reserved_state_roots()`가 이 두 값을 요구한다; 어떤 상태 디렉터리와도 겹치지 않는 예약 경로다).

### 환경변수 전체

| 이름 | 필수 | 기본값 | 의미 |
|---|---|---|---|
| `ZOOP_COLLECTOR_RUN_ID` | run/restore | — | `[A-Za-z0-9][A-Za-z0-9._-]{0,63}`. checkpoint는 `runs/<runId>/` 아래에 쌓인다. 같은 run의 대체 task는 같은 값을 쓴다. 새 수집은 새 값. |
| `ZOOP_COLLECTOR_S3_URI` | run/restore | — | `s3://<bucket>/<prefix>` |
| `PRIVATE_CONFIG`, `KOREA_CONFIG`, `OFFICIAL_CONFIG` | 하나 이상 | — | 설정의 컨테이너 경로(경로를 켠다) |
| `<P>_CONFIG_S3_URI`, `<P>_CONFIG_SHA256` | 쌍 | — | 위 |
| `KOREA_RIGHTS_EVIDENCE_S3_URI`, `KOREA_EXCLUSIONS_S3_URI` | 아니오 | — | 위 |
| `ZOOP_COLLECTOR_CHECKPOINT_INTERVAL_SECONDS` | 아니오 | 900 | 주기 checkpoint 간격. 0이면 주기 checkpoint 끔(요청·최종은 항상) |
| `ZOOP_COLLECTOR_DRAIN_SECONDS` | 아니오 | 40 | SIGTERM 후 진행 중 요청을 기다리는 시간 |
| `ZOOP_COLLECTOR_RECOVER_SECONDS` | 아니오 | 10 | 강제 종료된 모든 worker의 unknown 표시와 회수에 공유하는 시간 |
| `ZOOP_COLLECTOR_FINAL_SECONDS` | 아니오 | 50 | 최종 snapshot + upload + 검증 + 게시 프로세스 회수의 최대 시간 |
| `ZOOP_COLLECTOR_RESERVE_SECONDS` | 아니오 | 15 | 정리·종료 여유 |
| `ZOOP_COLLECTOR_STOP_TIMEOUT_SECONDS` | 아니오 | 120 | ECS `stopTimeout`과 같게 둔다. drain+recover+final+reserve가 이 값을 넘으면 시작을 거부한다 |
| `ZOOP_COLLECTOR_PAUSE_TIMEOUT_SECONDS` | 아니오 | 120 | 주기·요청 checkpoint가 worker 일시정지를 기다리는 최대 시간 |
| `ZOOP_COLLECTOR_RESTORE` | 아니오 | `auto` | `auto`=상태가 비어 있고 S3에 checkpoint가 있으면 latest 복원. `<seq>-<checkpointId>`로 특정 checkpoint 지정 |
| `ZOOP_COLLECTOR_IMAGE_REVISION` | 아니오 | 빌드 인자 | manifest `image.gitCommit` |
| `OPENDART_API_KEY` | OpenDART일 때 | — | §8 |
| `AWS_REGION` 등 AWS 표준 | — | ECS 제공 | boto3 기본 chain. 시험에서 `AWS_ENDPOINT_URL`로 로컬 S3 호환 endpoint를 쓸 수 있다 |

worker에는 `PATH`, `LANG`, `HOME`, 위 `ZOOP_*` 고정값, 각 경로의 `*_CONFIG`만 전달된다. `OPENDART_API_KEY`는 `official` worker에만 전달된다.

## 4. `run`의 수명주기

1. 설정 검증(`ZOOP_COLLECTOR_*`, 정지 예산). `/var/lib/zoop-collector/controller.lock`을 `flock`하지 못하면 exit 3.
2. 설정 공급·검증(§3).
3. 상태 디렉터리가 비어 있고 S3에 `latest.json`이 있으면 복원(§6). checkpoint에 기록된 `configSha256`/`stateDir`이 현재 설정과 다르면 `restore_config_changed`/`restore_state_dir_mismatch`로 거부(exit 2). 상태가 이미 있으면 로컬 상태를 이어서 쓴다.
4. 경로마다 worker를 띄운다(`start_new_session`: 별도 process group). worker는 명령 pipe로 `PAUSE`/`RESUME`/`STOP`을 받고 event pipe로 응답한다. 요청 경계(`private_intake._budget`, Korea의 channel/record 루프, official task 루프)에서만 확인하므로 요청 중간에는 멈추지 않는다.
5. 주기(`CHECKPOINT_INTERVAL_SECONDS`)마다, 그리고 `checkpoint` 요청마다 §5의 checkpoint를 한다.
6. 모든 worker가 끝나면(예산·큐 소진·`admission_stopped`) 최종 checkpoint를 올리고 종료한다. SIGTERM/SIGINT는 §7.

`status.json`(`/var/lib/zoop-collector/control/`)에는 phase, worker별 pid·exitCode·결과 요약, 마지막 checkpoint가 있다. 포인터 쓰기 결과를 확인하지 못하면 `publicationUnknown`에 `manifestKey`와 원인을 기록한다(§7). 로그는 stderr의 JSON 한 줄씩(CloudWatch)이다: `controller_started`, `worker_started`, `checkpoint_uploaded`, `checkpoint_failed`, `stop_requested`, `drain_deadline_exceeded`, `recovered`, `final_checkpoint_failed`, `path_failed`.

### Exit code

| code | 의미 |
|---|---|
| 0 | 모든 경로가 끝났고(완료 또는 예산 stop으로 partial, 또는 SIGTERM으로 중단) **최종 checkpoint가 S3에 올라 검증됨** |
| 2 | 설정·시작 거부(`config_refused`: 환경변수, 설정 sha256, 지원하지 않는 설정, 고정 경로 위반, 정지 예산 초과, 복원 불일치, 누락된 secret) |
| 3 | 다른 controller가 같은 state root를 쓰는 중 |
| 4 | 최종 checkpoint 업로드/검증 실패 또는 포인터 쓰기의 원격 결과 불명(§7) |
| 5 | checkpoint는 올렸지만 경로가 실패함(worker `refused`·비정상 종료, 강제 종료 후 unknown 표시 실패) |
| 6 | restore 실패(`restore` 명령, 또는 `run` 시작 복원) |
| 7 | `checkpoint` 명령: 살아 있는 controller 없음 |
| 8 | `checkpoint` 명령: 응답 시간 초과 |

`status`는 항상 0. `checkpoint` 명령은 성공 0, 실패 4(controller의 `ok:false`).

## 5. 일관된 checkpoint

checkpoint는 **실행 중인 controller가 정지점에서** 만든다. 바깥(`checkpoint` 명령)은 요청 파일(`control/requests/<id>.json`)을 놓고 응답(`control/responses/<id>.json`)을 기다릴 뿐 상태를 읽지 않는다.

1. 모든 worker에 `PAUSE`. 각 worker는 다음 요청 경계(저장이 끝나고 진행 중 요청이 없는 지점)에서 확인하고 멈춘다. 이미 끝난 worker는 정지 상태로 친다. 시간 내 못 멈추면 `RESUME` 후 `pause_timeout`(다음 주기에 재시도). SIGTERM이 오면 즉시 중단.
2. 별도 프로세스가 각 상태 트리를 staging(`/var/lib/zoop-collector/checkpoints/<seq>-<id>/`)에 복사한다. SQLite 파일(헤더 `SQLite format 3\0`)은 **online backup API**(`sqlite3.Connection.backup`)로 새 파일에 쓰고 `PRAGMA quick_check`가 `ok`여야 한다. live `-wal`/`-shm`/`-journal`은 복사하지 않는다. 나머지 닫힌 일반 파일은 복사하며 sha256을 계산하고 복사 전후 inode·크기·mtime이 같아야 한다(다르면 `file_changed_during_copy`). `.stage-*` 임시 파일은 제외한다. symlink·특수 파일은 `unsafe_entry`로 거부하며 빈 디렉터리는 manifest `dirs`로 보존한다.
3. worker를 `RESUME`한다. **일시정지는 로컬 복사 동안만**이고 upload는 staging에서 worker와 병행한다. SIGTERM을 받은 뒤에는 worker를 재개하지 않는다.
4. 별도 게시 프로세스가 staging을 S3에 올린다(§6). 중단하거나 완료한 프로세스를 회수한 뒤 staging을 삭제한다.

SIGTERM 최종 checkpoint는 worker가 모두 끝난 뒤이므로 일시정지가 필요 없다.

## 6. S3 레이아웃, manifest, restore

```
s3://<bucket>/<prefix>/runs/<runId>/latest.json
s3://<bucket>/<prefix>/runs/<runId>/checkpoints/<seq:06d>-<checkpointId>/MANIFEST.json
s3://<bucket>/<prefix>/runs/<runId>/checkpoints/<seq:06d>-<checkpointId>/<private|korea|official>/<상대경로>
```

업로드 순서: 모든 파일(병렬 8, 각 파일은 `head_object`로 크기와 `sha256` metadata 확인; 이전 checkpoint와 sha256이 같은 파일은 서버 측 `copy_object`) → `MANIFEST.json`(올린 뒤 다시 읽어 바이트 대조) → 별도 프로세스에서 `latest.json` 쓰기 한 번. boto3 클라이언트는 각 프로세스에서 새로 생성한다. 포인터 쓰기의 SDK 재시도는 꺼져 있으며, 파일 전송의 기존 SDK 재시도도 전체 게시 deadline 안에서만 실행된다. 각 checkpoint는 자체로 완결되므로 오래된 것을 지워도 최신이 깨지지 않는다(보존 정책은 인프라의 lifecycle 소관).

`MANIFEST.json` (`zoop-collector-checkpoint-1`):

```json
{
  "schemaVersion": "zoop-collector-checkpoint-1",
  "runId": "smoke-3",
  "checkpointId": "b98aea21b733",
  "seq": 1,
  "kind": "final",
  "createdAt": "2026-10-29T11:32:09Z",
  "image": {"gitCommit": "251fcdf58096cc2549642280f08806c4352d5048", "package": "zoop-ai-pipeline"},
  "paths": [{"name": "private", "stateDir": "/var/lib/zoop-collector/private",
             "configSha256": "271480f5…", "unknownOutcomes": 2, "shutdown": "killed-marked-unknown"}],
  "dirs": ["private"],
  "files": [
    {"path": "private/STATE.json", "bytes": 939, "sha256": "5f1365e6…", "kind": "file"},
    {"path": "private/QUEUE.sqlite3", "bytes": 151552, "sha256": "cafa266e…", "kind": "sqlite"}
  ],
  "sqlite": [{"path": "private/QUEUE.sqlite3", "method": "backup"}],
  "unknownOutcomes": 2,
  "previous": {"seq": 5, "checkpointId": "…", "manifestSha256": "…"}
}
```

- `kind`: `periodic` | `requested` | `final`. `paths[].shutdown`: `running`(주기) | `exited` | `killed-marked-unknown`(drain 초과로 강제 종료 후 unknown 표시 완료) | `killed-unrecovered`. `unknownOutcomes`는 staged 상태의 `unknownRequests`(+ provider)와 unknown 상태의 항목 수다. `previous`는 직전 checkpoint 참조(첫 checkpoint는 `null`). `sha256`은 backup으로 만든 파일의 해시다(원본 DB 바이트가 아님).
- `latest.json` (`zoop-collector-latest-1`): `{schemaVersion, runId, seq, checkpointId, manifestKey, manifestSha256, updatedAt}`.

**restore**(`restore` 명령 또는 `run` 시작): `latest.json`(또는 지정 `<seq>-<id>`)의 manifest를 받아 `manifestSha256`을 대조하고 스키마·경로(`..`·절대경로·허용 이름 밖)를 검증한다 → `state root/.restore-<id>/`에 모든 파일을 받아 크기·sha256을 확인하고 **불필요한 파일이 없는지**까지 본다 → 대상 상태 디렉터리가 없거나 비어 있을 때만 rename으로 설치(0700/0600). 하나라도 어긋나면 상태 디렉터리를 만들지 않는다(`sha256_mismatch`, `size_mismatch`, `file_missing`, `unexpected_entry`, `manifest_sha256_mismatch`, `state_not_empty`). 복원 자체는 상태를 고치지 않는다. 정지점 상태이므로 in-flight·reserved 요청이 없고, 강제 종료로 끝난 경우는 이미 unknown으로 표시되어 있어 이어서 `resume`해도 **재전송하지 않는다**(기존 `recover()` 의미).

필요한 IAM(S3, 해당 prefix): `s3:GetObject`, `s3:PutObject`(`<prefix>/*`), 그리고 없는 키가 403이 아닌 404로 돌아오도록 `s3:ListBucket`(첫 실행의 `latest.json` 조회에 필요).

## 7. SIGTERM (ECS: SIGTERM → `stopTimeout` 후 SIGKILL)

`tini`가 SIGTERM을 controller에 전달한다. controller는:

1. signal handler가 모든 worker의 process group에 즉시 SIGTERM을 보내 **새 admission을 중단**한다. 이어지는 drain에서 pipe의 `STOP`도 전달한다. 주기·요청 checkpoint의 복사나 업로드 중에도 이 신호 전달은 실행된다. worker는 다음 요청 경계에서 멈춘다(`admission_stopped`).
2. 주기·요청 checkpoint의 대기를 접고 게시 프로세스를 종료·회수한다. controller는 20ms 간격으로 취소를 확인한다. 취소된 파일 게시 프로세스는 `latest.json` 쓰기를 실행할 수 없다.
3. **drain**: SIGTERM 시각부터 `DRAIN_SECONDS`(40)까지 진행 중 요청을 기다린다. 끝나지 않은 worker는 process group에 SIGKILL을 보낸다.
4. **unknown 표시**: 강제 종료된 worker는 시작 시점부터 stop된 worker로 기존 `recover()`를 실행해 pendingRequest·attempting 항목을 unknown으로 바꾼다. 모든 복구 worker가 `RECOVER_SECONDS`(10)와 남은 종료 시간을 공유한다.
5. 최종 checkpoint를 게시한다. snapshot·전체 HTTP 요청(응답 body 읽기 포함)·SDK 재시도·executor 정리를 별도 프로세스에 격리하며, deadline이 닥치면 해당 프로세스를 강제 종료하고 회수한다. 프로세스별 잔여 시간의 1/4(최대 1초)을 회수에 남긴다.
6. 포인터 쓰기 응답과 프로세스 종료까지 deadline 안에 확인하면 exit 0, 아니면 4(경로 실패는 5)다.

시간 산술(120초 `stopTimeout`): drain 40 + recover 10 + 최종 checkpoint 50 + 여유 15 = **115 ≤ 120**. 시작 시 이 합이 `ZOOP_COLLECTOR_STOP_TIMEOUT_SECONDS`를 넘으면 거부한다. 최종 deadline은 **최종 단계 시작 + `FINAL_SECONDS`**와 **SIGTERM 시각 + `stopTimeout` − `RESERVE`** 중 이른 값이다. 정상 완료의 최종 게시에도 `FINAL_SECONDS`가 적용된다. socket read timeout은 전체 요청의 상한이 아니므로 종료 보장은 프로세스 감독이 맡는다.

**이전 latest 보존 조건:** 포인터 쓰기를 시작하기 전에 실패·취소되면 이전 `latest.json`을 유지한다. 이미 포인터 쓰기를 시작했는데 응답을 확인하지 못했다면 S3에서 적용됐을 수 있으므로 `remote_commit_unknown`과 `manifestKey`를 기록하고 exit 4로 끝낸다. 이때 최종 게시를 다시 실행하지 않는다. 운영자는 재실행 전에 remote latest와 해당 manifest의 sha256을 대조해 결과를 확인해야 한다. 자동 재전송·롤백·삭제로 불확실성을 덮지 않는다.

**기존 이미지 관측(아래는 종료 제한 수정 전 로컬 Docker/OrbStack·moto S3 기록이다)**

| 상황 | 관측 |
|---|---|
| 요청 1초씩 걸리는 수집 중 `docker stop -t 60` | SIGTERM→exit 0까지 2.9초, 최종 checkpoint 0.4초(87 파일) |
| 100초짜리 요청이 진행 중일 때 `docker stop -t 60` | `stop_requested` 11:31:28 → `drain_deadline_exceeded` 11:32:08(40초) → `recovered` +1초 → 최종 checkpoint 0.19초 → exit 0, 총 41초. `unknownOutcomes: 2`, `shutdown: killed-marked-unknown`. 해당 요청은 재전송되지 않음 |

## 8. 모드별 Secret 환경변수 이름 (코드에서 확인)

값은 Secrets Manager → ECS `secrets`로만 주입하고 설정 JSON에는 쓰지 않는다.

| 모드 | 이름 | 비고 |
|---|---|---|
| **수집 전용**(private news, Korea, official `fsc-press`/`federal-register-bis`/`sec-edgar`) — v1 기본 | **없음** | 모델 키 없음. `sec-edgar`의 company/contact는 비밀이 아닌 설정 필드 |
| 수집 + OpenDART(`official`, `sourceId: opendart`) | `OPENDART_API_KEY` | 40자 영숫자(`official_source_adapters.py`). `official` worker에만 전달. 없으면 `secret_missing`으로 시작 거부 |
| 수집 + 유료 DeepSeek fetch fallback(private `fallback`) | `DEEPSEEK_API_KEY`; 비밀 아님: `ZOOP_AI_PIPELINE_LIVE_SET_ID`, `ZOOP_AI_PIPELINE_LIVE_SEND_BEFORE`(선택) | 코드(`private_intake._FundedFetch`)가 읽는 이름이다. **컨테이너 `run`은 이 설정을 거부하며 이름을 worker에 전달하지 않는다**(§3). 지원하려면 budget ledger(`modelbudget/live-budget.sqlite3`)·set proof·fetch-pacing DB를 checkpoint에 넣는 별도 변경이 필요하다 |
| 분석 CLI(이 이미지의 `run`이 아님, 컨테이너 계약 밖) | `ZOOP_AI_API_KEY`(OpenAI 호환), `TYPESAFE_API_KEY`(Jev), `DEEPSEEK_API_KEY`(direct); 그래프: `ZOOP_GRAPH_USER`, `ZOOP_GRAPH_PASSWORD` | `live_runtime.py`, `direct_deepseek.py`, `graph_neo4j.py`. 게이트와 예산 변수(`ZOOP_AI_PIPELINE_LIVE_*`)는 비밀이 아니다 |

## 9. 다루지 않는 것

- 스케줄링, ECS Task Definition, 알림, S3 lifecycle/보존, 다중 task 동시 실행(같은 `runId`를 두 task가 쓰면 `latest.json`이 서로 덮인다. 하나의 task만 쓴다).
- 유료 fallback·예산 ledger·predecessor/continuation 설정(§3, §8). 분석(extract/relation/…) 단계의 컨테이너 실행. checkpoint는 수집 상태 트리 세 개만 담는다.
- 요청 **중간** 중단: 중단·일시정지는 요청 경계에서만이며, 진행 중 요청은 drain 안에 끝나지 않으면 강제 종료되고 unknown이 된다.
- 실행 시간 예산은 기존 의미대로 첫 시작(`startedAt`)부터의 벽시계다. 복원 후에는 정지 기간도 포함되어 `max_total_seconds`를 넘기면 `timeout` stop이 된다.
- 자동 재시도·재전송. unknown은 새 plan으로만 다룬다.
- 실제 AWS(ECR push, S3, IAM, Fargate stop 동작)는 검증하지 않았다. 아래 검증은 로컬 Docker와 S3 호환 서버(moto, 프로젝트 의존성 아님)다.

## 10. 검증 방법

CI와 같은 작업 디렉터리를 사용하도록 저장소 루트에서 실행한다.

```sh
uv run --project ai/pipeline --frozen --group dev python -m pytest \
  ai/pipeline/tests/test_collector_container.py -n 4 --dist loadfile -q
```

컨테이너 smoke: 같은 네트워크에 S3 호환 서버와 loopback fixture 서버를 두고(`synthetic loopback` 설정은 `127.0.0.1`만 허용하므로 fixture 컨테이너의 network namespace를 `--network container:<fixture>`로 공유), `PRIVATE_CONFIG_S3_URI`+`SHA256`·`ZOOP_COLLECTOR_S3_URI`·`AWS_ENDPOINT_URL`을 주고 `run` → 주기 checkpoint → `docker exec … zoop-ai-collector checkpoint` → `docker stop -t 60` → 새 컨테이너에서 `restore`/`run`.

위 시험은 실제 worker 프로세스·SIGTERM과 unsigned boto3 → stdlib loopback S3 서버를 사용한다. 5초 종료 예산의 업로드 중 SIGTERM, 2초 게시 예산의 늦은 파일 전송·503 재시도·응답 body trickle, 포인터 수락 후 응답 유실을 검사한다. 이전 checkpoint 복원·unknown 보존·재전송 방지와 정상 주기·요청·최종 checkpoint도 포함한다. 실제 AWS/IAM/Fargate, 수정한 이미지 빌드, 대규모 상태의 로컬 디스크 지연은 이 시험의 검증 범위 밖이다. 프로세스 종료·회수는 OS가 SIGKILL을 처리할 수 있다는 전제이며, task의 최종 강제 종료 상한은 ECS `stopTimeout=120`이 맡는다.
