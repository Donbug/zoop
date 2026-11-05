# API Dev 배포 절차

## 1. 현재 상태

API Dev 배포 워크플로는 컨테이너 이미지 준비와 ECS 배포 절차를 제공한다.

현재 Dev 인프라와 애플리케이션 실행 조건이 모두 준비되지 않았으므로 실제 배포는 HOLD 상태다. 승인 없이 Terraform Apply 또는 ECS Service 활성화를 수행하지 않는다.

## 2. 워크플로 실행 방식

GitHub Actions의 `Deploy API to Dev` 워크플로는 수동 실행만 지원한다.

실행 시 다음 operation 중 하나를 선택한다.

| operation | 동작 |
|---|---|
| `stage-image` | ECR 이미지 준비만 수행하고 ECS는 변경하지 않는다 |
| `deploy` | ECR 이미지를 준비한 후 ECS Task Definition과 Service를 갱신한다 |

기본값은 `stage-image`다.

PR 및 일반 Push 이벤트에서는 AWS 인증, ECR Push 또는 ECS 배포를 실행하지 않는다.

## 3. 불변 이미지 처리

API 이미지는 Git Commit SHA를 ECR 태그로 사용한다.

워크플로는 다음 순서로 이미지를 처리한다.

1. 현재 Commit SHA 태그가 ECR에 존재하는지 조회한다.
2. 이미지가 존재하면 다시 빌드하거나 Push하지 않는다.
3. 이미지가 없을 때만 Docker Build와 ECR Push를 수행한다.
4. Push 완료 후 ECR에서 Image Digest를 조회한다.
5. ECS Task Definition에는 태그가 아니라 Digest 기반 이미지 URI를 전달한다.

이 방식은 ECR의 Immutable Tag 정책을 유지하면서 부분 실패 후 동일 커밋을 안전하게 재실행하기 위한 것이다.

## 4. ECS desired count 0

Terraform의 기본 `api_desired_count`는 0이다.

`desiredCount=0`은 API 실행이 의도적으로 비활성화된 상태를 의미한다. 이 상태에서 ECS Service가 안정 상태로 표시되더라도 API 컨테이너, Flyway 및 HTTP Health Check가 실행됐다는 뜻은 아니다.

따라서 `deploy` operation은 ECS Service의 Desired Count가 1 이상인 경우에만 실행한다.

Desired Count가 0이면 워크플로는 배포를 중단하며 자동으로 Task 수를 올리지 않는다. 서비스 활성화는 승인된 Terraform 변경을 통해 수행한다.

이미지만 준비해야 하는 경우에는 `stage-image`를 사용한다.

## 5. PR Docker 검증

PR CI의 `api-container` job은 다음 명령과 같은 컨테이너 빌드를 수행한다.

```bash
docker build \
  --file api/Dockerfile \
  --tag "zoop-api:ci-${GITHUB_SHA}" \
  api
```

이 검증에서는 다음 작업을 수행하지 않는다.

- AWS 자격 증명 발급
- Amazon ECR 로그인
- 이미지 Push
- ECS Task Definition 등록
- ECS Service 갱신
- 실제 애플리케이션 배포

### 5.1. 로컬 컨테이너 생존 확인

이미지 빌드 성공만으로 API 기동이나 `/health` 응답을 확인할 수는 없다. `/health`는 인증 없는 프로세스 생존 확인용이며, 응답·메서드·DB 기동 조건은 [API 실행 환경](../../api/README.md#프로세스-생존-확인)에 정의한다.

실제 배포 전에 다음 시나리오를 로컬에서 별도로 확인한다. 이 절차는 검증 방법이며, 검증 완료 기록이나 AWS 배포 승인이 아니다.

1. 위 Docker 명령으로 이미지를 빌드하고, 검증용 일회용 PostgreSQL을 준비한다. Flyway와 시작 시 기업 카탈로그 import가 DB를 변경하므로 공유 DB나 보존할 DB를 사용하지 않는다.
2. API 컨테이너에 해당 DB의 `DB_URL`·`DB_USERNAME`·`DB_PASSWORD`와 검증용 `ZOOP_AUTH_CSRF_ACTIVE_KEY_ID`·`ZOOP_AUTH_CSRF_KEYS`를 주입한다. 기존 `.env`나 운영 Secret을 복사하지 않는다. `ZOOP_AI_CLIENT_ENABLED`·`ZOOP_AI_EXTRACTION_CLIENT_ENABLED`·`ZOOP_AI_RELATION_CLIENT_ENABLED`·`ZOOP_AI_CHAT_CLIENT_ENABLED`는 모두 `false`로 두고 AI 서비스는 띄우지 않는다.
3. `SERVER_PORT=8080`, 포트 매핑 `127.0.0.1:8080:8080`으로 실제 API 이미지를 실행한다. DB 자동 설정·Flyway·JPA를 제외하지 않는다. 앱 기동과 `Confirmed company catalog ready` 로그를 확인한 뒤 아래 요청을 인증 헤더나 쿠키 없이 실행한다.

   ```sh
   curl --fail-with-body --max-time 5 -i http://127.0.0.1:8080/health
   curl --max-time 5 -I http://127.0.0.1:8080/health
   curl --max-time 5 -i -X OPTIONS http://127.0.0.1:8080/health
   curl --max-time 5 -i -X POST http://127.0.0.1:8080/health
   ```

   GET은 200과 `{"status":"UP"}`, HEAD는 200과 빈 본문, OPTIONS는 200과 GET·HEAD·OPTIONS 허용, POST는 기존 오류 형식의 405여야 한다.
4. **이 검증에서 직접 만든 DB 컨테이너만** 중지하고, API 컨테이너는 재시작하지 않은 채 같은 GET을 다시 실행한다. 여전히 200과 동일한 최소 본문을 반환하는지 확인한다. 이 결과는 기동 후 DB 장애와 생존 응답의 독립성을 보여 주며, DB가 없는 상태에서 전체 API를 처음 기동할 수 있다는 증거는 아니다.
5. 검증용 API·DB 컨테이너와 직접 만든 임시 자원만 정리한다. 응답과 종료 상태를 기록하되 Secret·쿠키·연결 자격 증명을 증거에 포함하지 않는다.

## 6. GitHub Environment 설정

실제 워크플로 실행 전 GitHub `dev` Environment에 다음 변수가 필요하다.

| 변수 | 용도 |
|---|---|
| `AWS_REGION` | AWS 리전 |
| `AWS_IMAGE_STAGE_ROLE_ARN` | `stage-image` 실행 시 사용하는 API ECR 전용 GitHub OIDC 역할 |
| `AWS_DEPLOY_ROLE_ARN` | `deploy` 실행 시 사용하는 ECR·ECS 배포용 GitHub OIDC 역할 |
| `API_ECR_REPOSITORY` | API ECR Repository 이름 |
| `API_ECS_CLUSTER` | ECS Cluster 이름 |
| `API_ECS_SERVICE` | API ECS Service 이름 |
| `API_ECS_TASK_DEFINITION` | API Task Definition 이름 |
| `API_ECS_CONTAINER_NAME` | Task Definition 내부 API Container 이름 |

`stage-image`는 API ECR Repository에만 접근 가능한 최소 권한 역할을 사용한다. `deploy`는 이미지 준비와 ECS Task Definition 및 Service 갱신에 필요한 별도 배포 역할을 사용한다. 두 operation이 하나의 IAM 역할을 공유하지 않는다.

실제 Secret 값은 저장소 코드나 문서에 기록하지 않는다.

## 7. 실제 배포 전 조건

다음 조건을 모두 확인한 후에만 `deploy`를 실행한다.

- [ ] Terraform Dev 인프라 적용 완료
- [ ] GitHub `dev` Environment 변수 등록
- [ ] GitHub Environment 필수 승인자 설정
- [ ] 허용된 배포 브랜치 설정
- [ ] API 런타임 환경변수 연결
- [ ] DB 접속 Secret 연결
- [ ] CSRF 서명 관련 Secret 연결
- [ ] 배포 대상 이미지의 API `/health` 응답 및 기동 후 DB 중단 시 독립성 확인
- [ ] ALB Target Group Health Check 확인
- [ ] ECS Desired Count 1 이상
- [ ] Flyway Migration 검토
- [ ] DB Migration 실패 및 롤백 절차 검토
- [ ] 배포 담당자 승인

## 8. 재실행 및 장애 복구

ECR Push 이후 ECS 배포가 실패한 경우 같은 Commit SHA로 워크플로를 다시 실행할 수 있다.

재실행 시 기존 ECR 이미지를 조회하고 같은 Digest를 재사용한다. Immutable Tag에 동일 태그를 다시 Push하지 않는다.

ECS 배포 실패 시 다음 항목을 확인한다.

- ECS Service Event
- Task 종료 코드
- CloudWatch Log
- ALB Target Health
- API `/health` 응답
- 필수 환경변수 및 Secret 연결
- Flyway Migration 결과

애플리케이션 이미지 롤백은 DB Migration을 자동으로 되돌리지 않는다. DB 변경이 포함된 배포는 별도의 Migration 복구 절차를 검토해야 한다.

## 9. 현재 배포 보류 항목

현재 다음 항목이 완료되기 전까지 실제 배포를 수행하지 않는다.

- API 런타임 환경변수와 Secret 연결
- 실제 API 컨테이너 8080 포트의 `/health` 응답 및 기동 후 DB 중단 시 독립성 검증
- Terraform 실제 적용
- GitHub `dev` Environment 보호 규칙 설정
- 프론트엔드와 백엔드 배포 준비 완료
