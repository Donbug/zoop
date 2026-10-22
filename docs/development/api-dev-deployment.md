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

## 6. GitHub Environment 설정

실제 워크플로 실행 전 GitHub `dev` Environment에 다음 변수가 필요하다.

| 변수 | 용도 |
|---|---|
| `AWS_REGION` | AWS 리전 |
| `AWS_ROLE_ARN` | GitHub OIDC 배포 역할 |
| `API_ECR_REPOSITORY` | API ECR Repository 이름 |
| `API_ECS_CLUSTER` | ECS Cluster 이름 |
| `API_ECS_SERVICE` | API ECS Service 이름 |
| `API_ECS_TASK_DEFINITION` | API Task Definition 이름 |
| `API_ECS_CONTAINER_NAME` | Task Definition 내부 API Container 이름 |

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
- [ ] API `/health` 엔드포인트 구현
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
- `/health` 엔드포인트 구현
- Terraform 실제 적용
- GitHub `dev` Environment 보호 규칙 설정
- 프론트엔드와 백엔드 배포 준비 완료
