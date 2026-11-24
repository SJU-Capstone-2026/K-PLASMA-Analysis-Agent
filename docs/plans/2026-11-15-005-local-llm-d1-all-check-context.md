---
title: "LocalLLM v2.4: 모든 검사의 설명 선별 보완"
date: 2026-11-15
type: perf
artifact_contract: ce-unified-plan/v1
artifact_readiness: implementation-ready
execution: code
product_contract_source: user-approved-all-check-context
---

# LocalLLM v2.4: 모든 검사의 설명 선별 보완

## Goal Capsule

사용자가 승인한 후속 구현이다. 항상 생성하는 3개 누락 검사는 검사별 고정 설명 묶음을 사용한다. 나머지 10종류도 검사 종류·단계·지표·참조에 맞는 설명을 제공한다. 검토 지침·선택지·검사 생성 조건·그래프·최종 응답은 바꾸지 않는다.

이전 [v2.4 계획](2026-11-15-004-local-llm-d1-per-check-context.md)의 `policy_full` 범위와 비교 후 full 복구 결정은 이번 사용자 지시로 대체한다. 기존 결과를 덮어쓰지 않는다. 이번 실제 평가는 직전 정상 5개·오류 5개 전체 10사례에 대해 선별 모드로만 한 번 수행하고, full 및 부분 선별 기준 성적은 보존한 기록과 비교한다. 이 범위를 최초 진행 보고에 명시했다.

## Planning Contract

- `request.tasks`: 모든 도구의 역할·입출력과 지표 식별 정보를 고정 제공한다. 긴 지표 계산 정의는 해당 출력 검사에서 다룬다.
- `request.filter_coverage`: 조회·검색·참조 규칙과 검색 가능한 6개 지표의 정의를 고정 제공한다. 계획에 없는 요청 필터도 검토할 자료를 남긴다.
- `request.confirmation_coverage`: 사용자 확인·비교 대상/기준 연결·값 참조 규칙을 고정 제공한다.
- `outputs`: 등록된 32개 지표 정의와 그래프/비교 규칙을 유지하면서 무관한 도구 설명을 제외한다. 계획에 적힌 지표만 남기지 않는다.
- `ordering`: 목표가 비어 있어도 6개 검색 가능 지표와 정렬 규칙을 제공한다. 빈 목표가 자동 전체 fallback의 원인이 되지 않도록 한다.
- `filter`, `targets`, `baseline`, `trend_axis`는 기존 지표군·단위·선행 참조 보호를 유지한다. `operation`, `selection_count`, `selection_targets`, `execution_guards`도 해당 검사에 필요한 설명을 선택한다.
- 고정 원문에서 필드·설명 묶음을 복사한다. 새 자연어 파서·LLM·번역·설명 요약을 추가하지 않는다.
- 질문·이력·전체 계획·문맥·지침·선택지·정책·원본 snapshot/digest는 보존한다. 변경 본문은 `tool_contracts`뿐이다.
- 알 수 없는 표현·registry·참조의 전체 fallback과 기존 입력 오류/한도 차단은 유지한다. 다만 이번 전체 선별 평가는 모든 62개 검사가 `selected`여야 하며, full/fallback을 성공으로 세지 않는다.
- Q8+MLX 단일 처리, 영어 축약 프로필, Qwen 캐시 OFF, Docker 1536MiB, development 메모리 정책, d1 검토 ON·최대 2회 재계획/1회 답변 재작성을 유지한다.

## Implementation Units

1. U1: `core/d1_context.py`의 정책을 13종류로 확장하고 CPU 테스트를 먼저 작성한다. 고정 세트의 계획 독립성, 누락 가능 항목 보존, 참조·지표군·정의 연결과 원본 불변을 검증한다.
2. U2: `evals/local_llm_d1_context_probe.py`에 모델 호출 전 62개 전부 선별 검사와 실제 count/추론의 전부 선별·state hash 일치 관문을 추가한다. 실패 결과도 비공개 원본으로 보존한다.
3. U3: 소스를 동결한 후 새 정책의 메모리 증거를 만들고 같은 10사례를 선별 모드로 평가한다. 기존 전체/부분 선별과 비교하고 새 선별 모드로 공용 로컬 워커를 준비한다. 설명 선택 이외의 계산이나 모델 score/readout은 바꾸지 않는다.

## Verification Contract

Frozen corpus는 이전과 동일한 10사례·62개 검사, SHA-256 `c27853259c724b75e8851af094974b5b3b4ef0256c728f8182510e1136a98c87`다. 원시 파일은 Git 제외 경로를 사용한다. 정답표·사례 순서·모델·지침·선택지를 결과에 맞춰 수정하지 않는다.

| 단계 | 실제 추론 요청 상한 |
|---|---:|
| CPU·선별 완전성·native count | 0 |
| 새 per_check 정책 메모리 준비 | 7: Qwen 4+d1 3 |
| 같은 10사례 선별 평가 | 10 |
| 선별 설정으로 워커 준비 | 최대 4: Qwen 3+d1 1 |
| 합계 | **최대 21** |

count 호출은 추론과 분리 기록한다. full 기준 재평가·추가 의미 검토·자동 재시도·warmup은 수행하지 않는다. 메모리/프로토콜 실패나 불완전한 선별이면 부적합 상태를 그대로 보고하고 예산 밖 호출을 추가하지 않는다.

모든 실제 평가 전에 모델 설정과 실제 그래프 상태의 `plan_review_enabled=true`를 확인한다. 같은 원본 계획의 첫 검토를 비교하므로 실제 REPLAN·웹 질문 평가는 실행하지 않는다. 코드의 기존 복구 예산은 유지한다.

판정/정확한 항목/사유/추가 오판/엄격 선택 벡터, 62개 실제 입력·도구 설명 부분 토큰, 요청·검사별 시간, load/release/count, allocator·RSS·OS 메모리·압력·swap·Docker/DB OOM을 구분해 보고한다. 10사례 1회 결과를 일반 정확도 증명으로 해석하지 않는다. 이 10사례에 없는 계산·선택·실행 조건 검사는 CPU 보존 검증만으로 모델 정확도까지 검증했다고 주장하지 않는다.

## Definition of Done

- 13종류 선별 정책과 원본·누락·참조 보호의 CPU 검증 통과.
- 고정 10사례의 모든 62개가 실제 선별·계수·추론에 일치하며 full/fallback 0임을 확인.
- 새 소스 identity에 맞는 메모리·프로토콜 준비와 d1 ON 확인.
- 실제 평가 10회와 별도 준비 호출 수, 기준 대비 정확도·토큰·시간·메모리·미해결 오류를 모두 기록.
- 공용 웹/backend/DB와 과거 기록을 보존하고 선별 모드의 로컬 워커를 준비. 다른 앱과 v2/v3는 변경하지 않음.
- 원시 산출물은 비공개 로컬 보관. commit/push/PR은 요청 전 실행하지 않음.
