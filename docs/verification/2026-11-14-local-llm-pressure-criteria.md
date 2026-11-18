# 19.67GiB 정상·19.63GiB 경고의 판정 기준 확인

## 직접 확인한 결론

19.67GiB와19.63GiB는 통과 임계값이 아니다. 프로젝트가 출력한 메모리 합계와 커널이 경고를 결정하는 입력이 다르다.
현재 차단의 직접 조건은 **측정 중 OS 경고 표본이 하나라도 있으면 해당 준비 검사를 실패 처리하는 정책**이다.
단일 Qwen 호출은 정상 응답했으므로, 이 실패를 곧바로 추론 불가능·OOM으로 확대하지 않는다.

정리 후 추가로 수행한244토큰 단일 인공 진단은128표본 모두 정상으로 끝났다.
따라서 “정리 후에도 항상 같은 기본 호출이 실패한다”는 가설도 현재 증거와 맞지 않는다.
전체7행·캐시 왕복·웹 평가는 이번 원인 진단에서 실행하지 않았다.

## 1. 프로젝트가 출력한 숫자와 실제 차단 조건

`runtime.py:397`의 `parse_memory_sample()`은 다음 값을 별도로 수집한다.

```text
pressure = sysctl kern.memorystatus_vm_pressure_level
resident_bytes = (active + wired + compressor 점유 페이지) × page_size
swap_bytes = vm.swapusage의 현재 used
```

`resident_bytes`는 일부 VM 통계의 합계다. inactive/free/speculative 페이지 등을 모두 표현하지 않으며,
Qwen 전용 메모리·GPU 전용 메모리·24GiB 전체 사용량의 완전한 분해도 아니다.
압력 파서는1/2/4를 정상/경고/심각으로 처리한다. Apple의 sysctl handler도 내부 enum을 dispatch 값으로 변환해 출력하므로 이 매핑은 맞다.

기존 `evals/local_llm_measure.py`는2초마다 표본을 수집한다. 각 모델 단계 전 최신 표본이 정상이 아니면 다음 단계 진행을 중단한다.
최종 `passed`는7행 통과 외에도 **모든 표본의 pressure가1, 추가 swap0, 실행 facts 불변**을 요구한다(`:181`).
`peak_resident_bytes`와 특정 GiB 상한을 비교하지 않는다. `verify_memory_report()`도 pressure가1이 아닌 표본이 있으면 거부한다(`runtime.py:117`).
실행 후 정상으로 돌아와도 같은 보고서의 과거 경고 표본은 남아 있으므로 그 시도는 실패다.

시작 전 `wait_for_stability()`는 두 모델이 sleep이고 정상 압력이5초 연속 유지되는지만 검사한다(`runtime.py:270`).
모델을 깨운 뒤에도 그 조건이 유지된다는 보증은 아니며, 이를 실제 인공 부하 검사에서 확인하도록 구성돼 있다.

또한 출력 피크는2초 표본 중 최대다. 사이의 순간 최대를 보장하지 않는다.
이전19.67GiB는7단계 전체, 이번19.63GiB는 첫 Qwen 단계에서 중단된 구간의 최대여서 동일 단계의 메모리 구성 비교도 아니다.

## 2. Apple 공개 커널의 경고 식

실행 장치의 커널은 Darwin24.6.0, `xnu-11417.140.69.711.44~1/RELEASE_ARM64_T6041`이다.
공개 기반 태그 `xnu-11417.140.69`를 확인했다. 배포 커널의 세부 패치·내부 변수 전체를 직접 읽은 결과는 아니다.
압축은 활성 상태이며, 아래 공개 기본식은 수집한 정상·경고 관측과 일치한다.

```text
N = active + inactive + free + speculative 페이지
C = compressor가 실제 차지한 페이지
A = N + C

macOS 3GiB 초과 장치의 공개 기본 정책:
정상 → 경고: N < 0.5 × A
경고 → 정상: N > 0.6 × A
```

즉 전체24GiB의50%를 사용하면 경고가 난다는 뜻이 아니다.
커널이 정의한 비압축 가용 페이지가, 비압축 가용 페이지와 압축 점유 페이지를 합친 풀에서 차지하는 비율이다.
N에는 이미 사용 중이지만 회수·압축 가능한 페이지도 포함돼 있으므로 N을 빈 RAM으로 읽지 않는다.
경고 진입과 복귀가 서로 다른 것은 상태가 계속 흔들리지 않도록 한 hysteresis다.

이 경로의 공개 기본 major compaction/swap threshold는0.4×A다. 따라서 경고가 발생해도 곧바로 swap 증가가 필수인 것은 아니다.
실제 swap 동작은 다른 조건도 관여하므로 이 수치로 swap 발생 시각을 단정하지 않는다.

근거는 [가용 페이지 정의](https://github.com/apple-oss-distributions/xnu/blob/xnu-11417.140.69/osfmk/vm/vm_page.h),
[임계값 매크로](https://github.com/apple-oss-distributions/xnu/blob/xnu-11417.140.69/osfmk/vm/vm_compressor_xnu.h),
[macOS 기본 divisor](https://github.com/apple-oss-distributions/xnu/blob/xnu-11417.140.69/osfmk/vm/vm_compressor.c),
[경고 진입·복귀 판정](https://github.com/apple-oss-distributions/xnu/blob/xnu-11417.140.69/osfmk/vm/vm_pageout.c),
[sysctl 사용자 값 변환](https://github.com/apple-oss-distributions/xnu/blob/xnu-11417.140.69/bsd/kern/kern_memorystatus_notify.c)이다.

## 3. 기존 통과·실패 기록과 새 정밀 진단

이전3GiB 검사와 함께 수집한236개 독립 관측에서 N/A는50% 아래로 내려가지 않았다.
97표본 준비 보고서의19.666GiB 피크와 아래 독립 관측19.660GiB는 표본 시각이 달라 동일 숫자로 맞추지 않는다.

| 실제 관측 구간의 가장 낮은 비압축 비율 | N | C | N/(N+C) | OS 결과 |
|---|---:|---:|---:|---|
| 이전3GiB 통과 검사의 독립 관측 | 7.265GiB | 7.133GiB | 50.46% | 정상1 |
| 도구 정리 전 단일244토큰 진단 | 5.889GiB | 8.792GiB | 40.11% | 경고2 |
| 도구 정리 후 이번 정밀 단일244토큰 진단 | 7.626GiB | 7.333GiB | 50.98% | 정상1 |

정리 전 진단에서는 경고 상태의 최대 비압축 비율이59.96%, 정상 상태의 최소 비율이60.10%였다.
관측 시차를 고려해 경계점 자체로 단정하지 않지만, 공개 복귀 기준60%와 맞는다.

새 진단은 같은 모델·설정·Docker3GiB·공용 서비스·d1 검토 ON을 유지하고 계획 디스크 캐시 OFF에서 실행했다.
인공 웹 스택과244토큰 writer 호출1회만 사용했고 실제 질문·실험 데이터는 입력하지 않았다.
0.25초 대기 간격으로 VM 구성과 압력을 읽고, `vm_stat` 전후의 압력도 기록했다. 압력 생성·강제 purge·추가 앱 종료는 하지 않았다.
128표본 모두1, 추가 swap0, resident 피크19.514GiB였다. 모델 인자와 facts는 전후 동일했고 종료 후 두 모델은 sleep, 압력1이었다.
이는 진단 결과이며 새 전체 준비 보고서가 아니다.

중요한 한계: **마지막19.626GiB 실패 보고서는 N/C 상세를 저장하지 않았다. 그 순간의 정확한 비율과 일시적 변화는 복원할 수 없다.**
그 실패의 직접 코드 경로가 OS값2였다는 것은 확정할 수 있지만, 표의 다른 진단 값을 그 시점의 값처럼 대신 쓰지 않는다.

## 4. 정리 후에도 차단될 수 있는 이유

종료29개의 직전 footprint 합계2.12GiB는 즉시 회수한 물리 RAM2.12GiB가 아니었다.
정리 직후 관측 resident 감소는 약0.403GiB, compressor 감소는 약0.684GiB였고 일부 회계는 이미 swap에 있던 메모리였다.
Qwen을 깨울 때 필요한 모델·실행 공간은 같은 설정으로 유지된다.
새 정상 진단에서도 N/A 최저값은50.98%로 경고 진입 경계에서 약1%p 여유뿐이었다.
조금 다른 wired/압축/비압축 구성이나 순간 수요로 경고에 들어갈 수 있고, 한 번 경고가 되면 정상 복귀에는60%를 넘어야 한다.
프로젝트의 경고0 정책은 그 과정을 관측하면 해당 시도 전체를 거부한다.

따라서 직접 차단 원인은 “19.63GiB가 상한 초과”가 아니라 **경고가 발생한 OS 상태와 경고 표본0을 요구하는 준비 정책의 결합**이다.
상주 메모리의 감소는 확인됐지만, 모든 부하에서 무경고 여유가 확보됐다는 결론은 나오지 않았다.
반대로 단일 호출128표본 정상도 전체7행·장문 계획·d1·캐시 왕복·웹 평가 통과를 뜻하지 않는다.

기준·그래프·응답 형식·제품 코드는 수정하지 않았다.
원문 소스·읽기 전용 sysctl·정밀 VM 표본·기존 기록 교차검증은 Git 제외 경로
`.local/runtime/v2.2-qwen-cache/diagnosis/pressure-criteria/`에 보관했다.
`criteria-summary.json`의 정상/경고 비율 교차검증 assert가 통과했고, 기존 실행기의 실제 입력244·Qwen1회·인자 불변도 확인했다.
