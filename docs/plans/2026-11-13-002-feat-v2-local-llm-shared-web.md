# 공통 웹·백엔드·DB에서 v2_localLLM 선택하기 Implementation Plan

> **For agentic workers:** Use superpowers:executing-plans. 기존 독립 그래프를 유지하고 아래 작업을 순서대로 검증한다.

**Goal:** 5173의 같은 화면·백엔드·기존 DB에서 v1/v2/v3/v2_localLLM을 선택하고, 복구한 로컬 평가 채팅5개를 함께 조회한다.

**Architecture:** 사용자 확인 답변인 “웹·백엔드·DB 공유, LLM 경로만 분리”를 따른다. 상용 워커와 로컬 워커는 별도 프로세스·별도 인증 키를 사용한다. 백엔드는 키의 역할에 따라 claim과 요청별 내부 API 접근을 제한한다. Qwen·d1 실행 서버는 기존대로 유지한다.

**Tech Stack:** 기존 React/Vite, Spring Boot/PostgreSQL, Python 독립 그래프와 llama.cpp. 새 의존성 없음.

**Spec:** 이번 사용자 지시와 기존 독립 그래프 계획. 이 지시는 이전의 local-only 웹·DB 배포 제한을 대체한다.

## Global Constraints

- 그래프 구현·submit_plan·응답 필드·검증 기준·재계획/재작성 횟수와 모델 프로필은 그대로 유지한다.
- 로컬 요청은 상용 워커가 claim하거나 context·checkpoint·결과·입력·출력 API로 읽거나 쓸 수 없어야 한다. 반대 방향도 제한한다.
- local-only/기존 cloud-only 설정은 호환한다. 혼합 배포에서는 서로 다른 비밀 키가 필수다.
- 로컬 그래프가 포함된 배포는 기본 선택 버전과 무관하게 기존 loopback·Origin·세션 보호를 적용한다. 클라우드 fallback은 만들지 않는다.
- 기존150 Run과 기존 대화는 보존한다. 원본 DB·보관 볼륨을 먼저 백업하고, 복구한5개는 요청 UUID·과거 답변·실행 기록을 보존해 추가한다.
- 대화 epoch 충돌은 새 번호로 매핑하되 과거 답변/계획/수치 JSON을 현재 값으로 바꾸지 않는다. 매핑과 원본은 비공개 경로에 남긴다.
- 실제 질문 재평가·상용 API 호출·v3 실평가·commit/push는 이 작업 범위가 아니다.

## Review Focus

1. 상용 키가 v2_localLLM을 포함해 claim하거나 다른 요청 UUID를 직접 지정해 우회하는 경우도403으로 거부한다.
2. 혼합 배포에서 기본값을 상용 버전으로 설정해도 로컬 세션·프런트 CSP가 빠지지 않는다.
3. 동일 키·빈 로컬 키로 혼합 배포를 시작하면 명확히 실패한다.
4. 완료된 평가 기록을 복사할 때 활성 대화·기존 snapshot·새 사용자 작업을 덮어쓰지 않는다.
5. 브라우저로 과거 기록을 열거나 버전을 고르는 것만으로 새 LLM 질문을 제출하지 않는다.

## Task 1: 공통 배포와 워커 경계

**Files:** backend의 GraphVersionPolicy, AgentWorkerController, AgentRequestService, LocalRuntimeAccessFilter, application.yml와 관련 테스트.

**Interfaces:** 기존 내부 API·Claim 계약은 유지한다. `kplasma.agent.local-worker-token` / `AGENT_LOCAL_WORKER_TOKEN`으로 로컬 키를 제공한다. 기존 단일 로컬 배포에서는 기존 worker-token을 계속 사용할 수 있다.

- [x] 공유 배포의 버전 허용·세션 강제·역할별 claim/요청별 내부 API 거부·잘못된 키 설정 테스트를 먼저 추가하고 실패를 확인한다.
- [x] 기존 controller의 인증 지점에서 역할을 판별하고 모든 요청별 endpoint에서 그래프를 검증한다. 그래프·응답 생성 코드는 바꾸지 않는다.
- [x] 해당 테스트와 기존 local/cloud backend 회귀를 통과시킨다.

## Task 2: 기존 버전 선택 UI 연결

**Files:** frontend의 graph-versions, local-session, client, vite.config와 해당 테스트·AgentPage 테스트.

**Interfaces:** API는 계속 같은 `/api`를 사용한다. 혼합 버전도 기존 select에서 고른다. 대화의 그래프 고정·새 대화 규칙은 보존한다.

- [x] 혼합 버전 select·상용 기본값에서 로컬 bootstrap 선행 테스트를 실패부터 확인한다.
- [x] UI 배포 검증의 local-only 제한을 제거하고 로컬 버전 포함 여부로 인증·CSP 적용을 판단한다.
- [x] frontend 테스트·타입 검사·빌드와390/800/1008/1440px의 관련 화면을 확인한다.

## Task 3: 보존한5개 대화와 공통 실행 환경

**Files:** Git 제외 런타임 설정·백업·일회 복구 도구, 개발 문서·검증 기록.

- [x] 원본 DB를 백업하고 사본에서5개 대화 추가를 먼저 검증한다. 기존 기록과 답변 hash 불변, 원래5개 요청 UUID·완료 상태를 확인한다.
- [x] 정상 백엔드 JAR과 5173 프런트엔드를 현재 작업 폴더로 기동한다. 원래 상용 키는 유지하고 별도 로컬 키만 추가한다.
- [ ] 로컬 워커를 같은 백엔드에 연결한다. Qwen24K/batch256·d1 검토ON·Docker3GiB를 유지한다.
- [x] 승인된 공통 DB에 검증한5개를 트랜잭션으로 추가하고 기존150 Run·대화 보존을 다시 확인한다.
- [x] 기존 브라우저의 로컬 접속 인증을 갱신하고5173에서 선택과 과거 답변 조회를 확인한다. 새 실제 질문은 실행하지 않는다.
- [x] 별도5174 웹·8083 백엔드는 공통 환경 확인 뒤 소유 프로세스만 종료한다. 복구 원본·백업은 삭제하지 않는다.

## 실행 기록

사용자가 공통 웹·백엔드·DB 구성을 명시적으로 선택했다. 현재 `feat/v2-local-llm` worktree에서 기존 변경을 보존해 수행한다.
구현 전 파일 사본·진행 내역·실데이터 백업은 `.local/runtime/unified-web/`에 보존한다. 결과는 별도 검증 문서에 기록한다.

백엔드260개·프런트274개 테스트와 타입 검사·빌드가 통과했다. 공유 DB에5개 기록을 추가해150 Run·75개 답변·40개 대화·214개 요청을 확인했다.
검토 중 공통 판단 기록이 상용 워커의 기억 경로로 전달될 수 있는 문제를 발견해 RED→GREEN으로 수정했다.
V20은 공개 JSON을 유지하면서 내부 출처를 저장하고, 로컬·출처 불명 기록과 이를 담은 기존 pin을 상용 워커에서 차단한다.

로컬 워커 시작은 현재 호스트 메모리 경고(`LOCAL_MEMORY_PRESSURE`, level2)로 보류 중이다.
모델·Docker3GiB·기존 준비 기준은 바꾸지 않았으며 다른 앱을 종료하지 않았다. 비공개 시작 절차가 정상 메모리를 기다린 뒤 기존 준비 검사를 다시 실행한다.
따라서 로컬 워커의 READY와 새 질문 처리는 아직 완료로 판정하지 않는다. 자세한 결과는 `docs/verification/2026-11-13-v2-local-llm-shared-web.md`에 기록한다.
