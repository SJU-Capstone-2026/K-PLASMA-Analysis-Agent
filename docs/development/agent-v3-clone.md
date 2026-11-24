# Agent v3 독립 복제 — 1단계

v2 기준 소스 `51d077c9878b635c96da709eb7eb2aefd36699e1`에서 Python 에이전트 구현을 실제 복제했다.
보존 태그는 `agent-v2-baseline-20261111`이며 원본 SHA를 가리킨다.
RAG·새 규칙 기반 도구·ON/OFF·서버/DB/UI 활성화는 이 단계에 포함하지 않는다.
개발 규칙·비교 방법·복제 계획은 [문서 PR #34](https://github.com/SJU-Capstone-2026/K-PLASMA-Analysis-Agent/pull/34)에 분리했다.

## 복제 범위

[`clone-manifest.json`](../../agent/python/src/kplasma_agent/v3/clone-manifest.json)에
원본/복제 파일 경로, 모듈 경로, SHA-256과 허용한 식별자 변경을 기록했다.

| 경로 | 복제 내용 |
| --- | --- |
| `kplasma_agent/v3/graph.py` | 11개 노드와 기존 분기·HITL·재계획·재작성 |
| `kplasma_agent/v3/core/` | 계획 계약·검증·의미 검토·입력 연결·실행·답변 조립·입력 예산 |
| `kplasma_agent/v3/domain/` | 조회·검색·비교·수치와 근거 검증 |
| `kplasma_agent/v3/`의 지원 모듈 | 모델/서버 통신·스트리밍·진행·관측·설정·단위·공통 계약 |
| `kplasma_agent/v3/persistence/` | 체크포인트 adapter |

그래프, 모델 gateway, 실행 port, 체크포인트와 worker가 주입하는 입력 예산 검사를 시작점으로
내부 의존성을 추적한 36개 모듈이다. v2 모듈을 import하거나 같은 노드·함수·스키마 객체를 공유하지 않는다.
표준 라이브러리와 외부 패키지는 기존 잠금 버전을 사용한다.

## 허용한 차이

- 내부 import 경로를 `kplasma_agent.v3` 내부로 이동했다.
- builder·gateway·settings·port·그래프 답변 snapshot 클래스의 V2 식별자를 V3로 바꿨다.
- 그래프의 `implementationId`·`graphVersion`을 `v3`로 바꿨다. 계획 스키마 2·답변 스키마 1은 유지한다.
- 전용 설정 접두사를 `AGENT_V3_`로, 계획 trace 이름을 `v3.plan`으로 바꿨다.

이 외 실행 AST가 원본과 같은지 검사한다. 계획/답변 지시문과 도구 제출 스키마는 그대로다.
기본 계획·답변·Decisions 모델은 `gpt-6-luna`, 계획·답변 추론은 `low`, 호출 timeout은 90초다.
기존 재계획 최대 2회·답변 재작성 최대 1회와 호출 예산을 유지한다.
`AGENT_V2_` 설정으로 v3 계획 모델이나 검토 설정이 바뀌지 않는지 검사한다.

공통 지원 코드에 있는 과거 답변 스키마명과 호환용 도구 계약은 임의로 정리하지 않았다.
v3 계획에 노출되는 도구는 원본과 같은 `forward_lookup`, `reverse_search`, `compare_runs`, `explain_answer`다.
의사결정 기록의 새 규칙·RAG 검색 기능을 연결하지 않았다.

## 사용·검증 진입점

```python
from kplasma_agent.v3.graph import build_v3_graph
from kplasma_agent.v3.core.model_gateway import V3ModelGateway, V3Settings
from kplasma_agent.v3.core.backend import V3ExecutionPort
from kplasma_agent.v3.core.budget import check_payload
```

이 단계에서 graph builder는 메모리 또는 제공된 체크포인트·실행 port로 검증한다.
기존 worker의 버전 선택, 서버 허용 버전·DB 제약·UI 메뉴에는 v3를 등록하지 않았다.
따라서 현재 웹에서 v3를 선택하거나 기존 유료 평가 명령에 v3를 전달하는 단계가 아니다.

`agent/python`에서 실제 모델 호출 없이 실행한다.

```sh
uv run --frozen --extra tracing pytest -c pytest-v2.ini
uv run --frozen --extra tracing pytest -c pytest-v3.ini
uv run --frozen ruff check src tests/v3
uv run --frozen mypy src
```

CI에는 `Independent v3 clone and scripted parity` 검사를 추가했다. 유료 모델 평가가 아니다.

## 검증 결과

| 검사 | 결과 |
| --- | --- |
| 기존 v2·공통 회귀 | 349 passed / 6 deselected |
| v3 복제·기존 회귀·직접 대조 | 156 passed |
| Python Ruff | 통과 |
| Python mypy | 77개 소스 검사 통과 |
| 원본 보존·독립성 | 원본/복제 해시, 금지 import, 객체 분리, 식별자 외 AST·프롬프트·스키마 동일성 통과 |

직접 대조는 개념 답변, 데이터 조회, 의미 반려 후 재계획, 검토 불가 시 실행 중단,
HITL 체크포인트 재개, 과잉 해석 후 재작성을 포함한다. 최종 직렬화·호출 순서를 대조하며
그래프 버전 식별과 비결정적인 경과 시간만 정규화한다.
복제한 16개 회귀 검사 파일의 assertion은 namespace·식별자 치환 외에 변경하지 않았다.
타입이 있는 인공 계획 fixture와 고정 응답 helper도 v3 테스트용으로 복사했다.

## 후속 변경 시 주의

manifest와 AST 동등성 검사는 초기 복제 상태의 증거다. 향후 의도된 v3 기능 추가에서는
이 초기 기록을 보존하고 검증 범위를 새 기능·기존 동작 회귀로 명시적으로 갱신한다.
v2 원본 해시와 v3 내부 import 독립성 검사는 유지한다.
실제 LLM 정확도·웹/API v3 동작은 이번에 평가하지 않았다. 복제 완료와 전체 v3 활성화 완료를 구분한다.
