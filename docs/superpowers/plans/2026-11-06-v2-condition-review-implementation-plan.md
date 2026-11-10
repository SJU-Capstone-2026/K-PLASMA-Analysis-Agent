# v2 조건별 Decisions 검토 구현 계획

> **For agentic workers:** Use inline execution with test-first verification. User authorized implementation and regression evaluation in the current conversation. No push or PR.

**Goal:** 계획 의미 검토를 조건별로 나누고, 반려 위치·유형과 원문·실제 계획 값을 저장해 재계획에 전달한다.

**Architecture:** 기존 코드 검사 → Decisions → 최대 2회 재계획을 유지한다. 코드가 실행 계획의 필터·정렬·비교 대상·기준·계산·선택 개수를 식별하고, Decisions 한 요청에 독립 질문으로 보낸다. 원문의 의미를 코드 규칙으로 파싱하거나 새 일반 LLM을 추가하지 않는다. 누락된 필터·선택 단계와 독립 검색 그룹도 별도 범위 검사로 포착한다. Reasons는 API가 선택한 유형과 코드가 연결한 증거이며 자유형 생성 문장이나 내부 추론이 아니다.

**Tech Stack:** Python, Pydantic, LangGraph, existing Decisions HTTP gateway and evaluation harness.

**Spec:** 사용자 2026-11-06 조건별 검토·원문/계획 대조 기록·다른 오탐 재검증 요청; 기존 v2 설계·상세 계약과 2026-11-06 계획 의미 검토 계획.

## Global Constraints

- 기존 기능 브랜치에서 이어서 작업하며 v1·최종 해석 검토·UI를 변경하지 않는다.
- 한 계획 검토는 Decisions HTTP 요청 1회, 재계획 요청 전체 최대 2회, 전체 모델 예산 13회를 유지한다.
- 원문 수치·단위·참조·사용자 선택을 자동 수정하지 않는다. 입력과 실행 계획은 그대로 검토한다.
- 조건별 choice가 불일치 유형을 식별한다. 확률·confidence는 분기에 쓰지 않는다.
- 누락·중복·알 수 없는 이름/유형·부분 응답은 실행 승인이 될 수 없다. 과거 schema 1 기록은 읽되 새 승인으로 재사용하지 않는다.
- 실제 Run과 모델 원본 출력은 Git에서 제외한다. 기존 13쌍×3=78회 평가를 고정하고 실패 결과를 포함해 보고한다.
- 기본 off는 자동으로 바꾸지 않는다. 새 평가가 개선돼도 작은 표본의 일반화는 보장하지 않는다.

## Review Focus

1. 조건 전체를 빼도 검토 항목 자체가 사라져 통과하지 않아야 한다.
2. 150–160 범위와 gte/lte, target_range 표현은 실행 의미에 맞게 검토한다.
3. 미래 result_ref와 정상 대상·기준 선택은 데이터 부재로 오인하지 않는다.
4. 반려의 원문·계획 값·위치는 저장 입력에서 코드가 가져오며 모델이 만들어내지 않는다.
5. 오래된 PASS와 일부 조건만 반환한 응답은 새 도구 실행을 열지 못한다.

## Task 1 — 조건별 질문과 반려 증거

**Files:** `v2/plan_checks.py` (new), `v2/plan_review.py`, `tests/v2/test_plan_review.py` and new focused tests.

- [ ] RED: 필터·정렬 분리, 빠진 압력 조건의 누락 검사, 선택 개수·기준·max 연산 분리, 원문/계획 증거 저장, 미등록·누락 응답 거절을 검증한다.
- [ ] GREEN: stable check specs and native reason choices; schema 2 결과와 schema 1 읽기 호환을 구현한다. 정렬과 비교 부등호의 의미를 구분한다.
- [ ] Verify: focused pytest; no model calls in unit tests.

## Task 2 — 호출·재계획·저장 통합

**Files:** `v2/model_gateway.py`, `graphs/v2.py`, existing gateway/graph/runtime/evaluation scripted tests.

- [ ] RED: 조건별 질문 한 HTTP 요청, 반려 증거가 수정 계획 모델과 저장 결과에 도달, 일부 PASS 거절, 정상 HITL 승인 재사용을 검증한다.
- [ ] GREEN: 기존 예산·상태 전이에 연결하고 실제 생성한 조건 집합과 승인 결과를 대조한다.
- [ ] Verify: full Python tests and Ruff, relevant real HTTP artificial-data E2E.

## Task 3 — 고정 평가·운영 검증

**Files:** evaluation output/reporting and development/contracts/verification docs.

- [ ] 기존 정상/오류 13쌍을 변경하지 않고 각 3회 평가한다. P01·P11·P13, 누락·경계·단위·정렬·그룹 오류와 반려 위치를 개별 기록한다.
- [ ] 품질 점수·호출 수·지연·반려 증거를 이전 78회와 비교한다. 교정 실험이 필요하면 고정 평가와 구분하고 무한 보완을 하지 않는다.
- [ ] 사용자 원문·후속 입력 증거와 현재 PASS 일치를 코드 검토하고 필요한 수정만 적용한다. 재실행하고 기능별 커밋을 남긴다.
