# 합성 과거 브리핑 재생 시험

이 폴더는 실제 뉴스·공시·API 응답을 포함하지 않습니다. 시험 원문과 모델 출력·검증·사용량은 모두 직접 작성한 합성 자료입니다. 실제 권리나 모델 호출을 주장하는 자료가 아닙니다.

시험은 localhost의 이름에 `briefing_replay`가 포함된 폐기용 PostgreSQL DB와 UUID로 분리한 schema만 사용합니다. public 데이터는 삭제하거나 TRUNCATE하지 않습니다. 외부 뉴스·모델·시세 호출은 없습니다.

운영 read 기본값은 거절하며, 명시적 local profile·loopback 주소·재생 read 설정이 함께 있어야 과거 graphVersion NULL 결과의 화면 복원을 허용합니다. 그래프와 시장 지표 및 회차 비교의 미수집 상태를 `unavailable`로 보존합니다.
