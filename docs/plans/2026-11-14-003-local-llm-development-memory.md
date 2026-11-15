# Docker2GiB와 경고 허용 개발 평가 구현 계획

> **For agentic workers:** Use superpowers:executing-plans inline, test-first. 기존 캐시 구현을 다시 만들지 않는다.

**Goal:** Docker VM을2048MiB로 제한하고 로컬 개발 평가가 경고 때문에 시작부터 막히지 않게 한다.

**Architecture:** `MEMORY_POLICY=strict|development`를 명시한다. 기본 strict는 기존 pressure1·추가 swap0을 유지한다.
development에서는 pressure1/2를 허용하고 swap 변화를 관측값으로 보존한다.4·미지 상태·모델/계약 오류는 거부한다.
정책을 fingerprint·측정 프로필에 넣어 strict 통과와 섞이지 않게 한다. 그래프·질문·d1·응답 계약은 변경하지 않는다.

**Tech Stack:** 기존 Python/httpx/pytest, llama.cpp b12317, Docker Desktop CLI.

**Spec:** 사용자가 개발용 경고 허용 제안을 선택한 지시: “docker를 2Gib로 제한을 걸어. … 그리고 경고는 허용하는 식으로 해.”
이전 지시의 앞5문항 캐시 OFF/ON 웹 평가까지 이어서 수행한다.

## Global Constraints

- Docker VM2048MiB. 기존150 Run·150 version과 DB volume 유지, 정상 stop/start만 사용한다.
- Qwen9B Q4_K_M, context24576·batch/ubatch256·생각2048·출력6000·90초, d1 Q8_0·검토ON 유지.
- 정책은 명시 설정이며 기본 strict. development 보고서를 strict 준비 증거로 인정하지 않는다.
- warning과 swap 증가를 숨기거나0으로 바꾸지 않는다. 심각 압력4는 새 모델 단계와 준비 판정에서 거부한다.
- 입력 한도·모델 파일 검증·순차 상주·lease·재계획/재작성 횟수·도구·그래프·최종 응답 양식 유지.
- 원시 응답·캐시·DB·화면은 Git 제외 경로에 보관. 소스·문항·grader를 평가 중 수정하지 않는다.
- 결과는 개발 정책하의 성적으로 표시한다. commit/push·새 모델·OS 전체 차단은 범위 밖이다.

## Review Focus

1. 정책 오타나 미지 압력 값을 경고로 취급하지 않는가?
2. strict가 과거와 같이 warning·swap 증가를 거부하고 개발 보고서를 거부하는가?
3. 측정기·캐시 왕복·시작 검사·worker 반복 검사에 같은 정책이 적용되는가?
4. 심각 압력에서 다음 모델 호출 전에 중단하고, d1 검토를 생략하지 않는가?
5. Docker 재시작 후 DB 수치·볼륨·공용 웹과2GiB 설정이 보존되는가?

## 작업

- [x] Docker: 활동 요청0·데이터 수·volume·OOM 카운터 기록 → DB 정상 정지 → Desktop 정지 → MemoryMiB2048만 변경 → 시작 → DB·웹 확인.
- [x] RED: 명시 정책 설정·fingerprint, 경고/심각 판정, swap 기록·정책간 증거 격리, 안정화·모델 단계의 critical 차단 회귀 검사.
- [x] GREEN: config.py와 runtime.py의 공통 압력 판정, 측정기·캐시 probe에만 좁게 연결. 예시 설정·차이 manifest·문서 갱신.
- [x] 로컬 전체·공통 계약·lint·mypy 검사 및 변경 범위 검토.
- [x] 소스 고정 후2GiB/development로 새 실제7행·캐시 왕복 측정. profile·warning·swap·OOM·피크 기록.
- [x] 준비 확인 후 기존5173 웹에서 Q01~Q05 OFF/ON 각1회, 총10회. 새 대화만 사용하며 이전 기록은 보존한다.
- [x] 최초 계획·d1 지적·재계획·최종 자동 판정·UI 자동 검사·캐시 토큰·I/O 포함 시간을 구분해 보고한다. Q03 추가 답변 검토는 미완료로 명시한다.

## 변경 파일

- config.py: memory_policy 설정·유효값·fingerprint.
- runtime.py: pressure_allowed(), 개발 증거 검증·안정화·현재 준비 판정·개발 모델 단계 critical 차단.
- evals/local_llm_measure.py와 local_llm_cache_probe.py: 경고를 기록하며 진행, critical 중단, 정책 표시.
- tests/v2_local_llm/test_memory_policy.py: 새 행동 회귀. 기존 strict 검사도 유지한다.
- intentional-differences.json, .env 예시, 개발/검증 문서: 새 설정과 결과의 의미 기록.

기존 dirty branch의 선행 출력·캐시 변경은 보존한다. 검증 원문은 `.local/runtime/v2.2-memory-policy/`에 보관한다.
