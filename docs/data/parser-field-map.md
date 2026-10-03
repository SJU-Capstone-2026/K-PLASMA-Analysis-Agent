# Parser 필드 계약 v1 — v12.3.1

API 정의는 `docs/api/openapi.yaml`, TypeScript는 `agent/src/contracts/index.ts`, Java는 `RunDto`, `WorkspaceDto`, `ImportDto`의 nested record다. 모든 값은 유한 binary64 JSON number이며 표시 반올림을 scalar/샘플 저장에 적용하지 않는다. 조건 격자는 Pressure [2,4,6,8,10] × Source [100,200,300,400,500] × Bias [0,200,400,600,800,1000]이며 총 150 실제 Run이다. 질의 값은 격자 밖 값도 허용한다.

`runId`는 표시 string, `runVersionId`는 불변 내부 UUID string이다. 검색 `RunSummary.analysis`에는 아래 모든 scalar만 포함하고 `FullRun.analysis`는 이를 포함한 전체 배열/객체다. Summary에는 `iedDistribution`, `sourceFiles`도 없다. `sourceFiles.path`는 원본의 상대 표시 경로이며 내부 파일 시스템 경로는 응답하지 않는다.

| 필드 | 타입 | 단위·null 의미 | 분류 |
| --- | --- | --- | --- |
| runId / runVersionId | string / string UUID | 표시 식별자 / 불변 버전 | Summary/Full 메타 |
| pressure / sourcePower / biasPower | number | mTorr / W / W | Summary/Full 조건 |
| metrics.ionFlux / meanIonEnergy / iedWidth | number / number / number 또는 null | 10¹⁸ m⁻²s⁻¹ / eV / eV; Bias-off width null | Summary/Full 지표 |
| units.* | string (6개 키) | 원본의 pressure/sourcePower/biasPower/ionFlux/meanIonEnergy/iedWidth 단위 | Summary/Full 메타 |
| analysis.hasDistribution / strictConvergence | boolean | 출력 유효성 / 독립 잔차 기준; 엔진 완료와 다름 | Summary/Full scalar |
| analysis.finalResidualMax | number | a.u. | Summary/Full scalar |
| analysis.electronTemperature | number | eV | Summary/Full scalar |
| analysis.ionTemperature | number | eV | Summary/Full scalar |
| analysis.gasTemperature | number | eV | Summary/Full scalar |
| analysis.absorbedPower | number | W | Summary/Full scalar |
| analysis.alpha | number | a.u. | Summary/Full scalar |
| analysis.plasmaResistance | number | ohm | Summary/Full scalar |
| analysis.plasmaReactance | number | ohm | Summary/Full scalar |
| analysis.dcOffset | number 또는 null | V; Bias-off null | Summary/Full scalar |
| analysis.peakToPeak | number 또는 null | V; Bias-off null | Summary/Full scalar |
| analysis.currentDensityPeak | number | statampere/cm² | Summary/Full scalar |
| analysis.electronDensity | number | #/cm³ | Summary/Full scalar |
| analysis.ionDensity | number | #/cm³ | Summary/Full scalar |
| analysis.metastableDensity | number | #/cm³ | Summary/Full scalar |
| analysis.neutralDensity | number | #/cm³ | Summary/Full scalar |
| analysis.ionFluxRaw | number | #/cm²sec | Summary/Full scalar |
| analysis.metastableFluxRaw | number | #/cm²sec | Summary/Full scalar |
| analysis.neutralFluxRaw | number | #/cm²sec | Summary/Full scalar |
| convergenceStatus / qualityStatus / catalogStatus | string | 정상 완료 CONVERGED / 구조 검증 VERIFIED / READY; 실패 상태 별도 | Summary/Full 메타 |
| registeredAt / presentationScore / note | ISO 8601 string / number / string | 등록 정책 / 기존 표시 메타 / 출처 설명; 물리 점수 아님 | Summary/Full 메타 |
| sourceFiles[] | {name,type,size,status,path} string 필드 | 성공 PARSED; 고정 3/9개; size는 실제 byte 기반 KB/MB | Full 표시 계보 |
| iedDistribution[] | {energy:number,intensity:number} | eV, a.u.; Bias-off 빈 배열 | Full 그래프 |
| analysis.residualTrace[] | [number,number] | iteration, 최대 절대 잔차 a.u.; Bias-off에도 존재 | Full 그래프 |
| analysis.iad | [number,number][] 또는 null | degrees, a.u.; Bias-off null | Full 그래프 |
| analysis.iead | {angles:number[],energies:number[],values:number[],sourceShape:[number,number],angleRange:[number,number]} 또는 null | degrees / eV / a.u.; 각도→에너지 flat; Bias-off null | Full 그래프 |
| analysis.current / potential | {points:[number,number][],phaseRange:[number,number],sourceCount:number} 또는 null | rf cycle와 statampere/cm² / V; Bias-off null | Full 그래프 |
| analysis.density | {rows:[number,number[],number[]][],sourceShape:[number,number]} 또는 null | rf cycle, cm, #/cm³; 위상 우선; Bias-off null | Full 그래프 |

## 원본 위치·변환과 부재

| Fixture field | Required raw source | Conversion / absence |
| --- | --- | --- |
| `pressure` | INI `[Pressure].PRS`; solver `[PREASURE & INLET CONDITIONS] Pressure (mTorr)` | Direct, cross-check both and folder if present |
| `sourcePower` | INI `[SourcePower].Powerh`; solver `[SOURCE POWER CONDITIONS] PowerH (W)` | Direct, cross-check |
| `biasPower` | INI `[BiasPower].Sourceh0`; solver `[BIAS POWER CONDITIONS] Power1h (W)` | Direct, cross-check; condition section exists even Bias-off |
| `metrics.ionFlux` | solver `[ION FLUX AT THE SHEATH EDGE] Ar+` | Raw `#/cm^2sec` × `1e-14`, display unit `10¹⁸ m⁻²s⁻¹`; direct binary64 multiplication matches all 150 |
| `metrics.meanIonEnergy` | solver `[AVERAGE ION ENERGY AT THE SUBSTRATE] Ar+ (eV)` | Direct; not recomputed as IED weighted mean |
| `metrics.iedWidth` | Full unsampled IED | Algorithm below; Bias-off `null` |
| `analysis.electronTemperature` | `[TEMPERATURE PARAMETERS] Electron Temp. (eV)` | Direct |
| `analysis.ionTemperature` | Same section, `Ion Temp. (eV)` | Direct |
| `analysis.gasTemperature` | Same section, `Gas Temp. (eV)` | Direct; do not convert to kelvin |
| `analysis.absorbedPower` | `[HEATING PARAMETERS] Absorbed power (W)` | Direct |
| `analysis.alpha` | Same section, `alpha (a.u.)` | Direct |
| `analysis.plasmaResistance` | Same section, `Plasma resistance (ohm)` | Direct |
| `analysis.plasmaReactance` | Same section, `Plasma reactance (ohm)` | Direct |
| `analysis.dcOffset` | `[BIAS PARAMETERS] dc-offset (V)` | Direct Bias-on; Bias-off `null` |
| `analysis.peakToPeak` | Same section, `peak-to-peak (V)` | Direct Bias-on; Bias-off `null` |
| `analysis.currentDensityPeak` | `[SHEATH PARAMETERS] J0h_h (statampere/cm^2)` | Direct solver scalar, not maximum of displayed current; raw Bias-off value is zero |
| `analysis.electronDensity` | `[NUMBER DENSITY] E (#/cm^3)` | Direct |
| `analysis.ionDensity` | Same section, `Ar+` | Direct |
| `analysis.metastableDensity` | Same section, `Ar*` | Direct |
| `analysis.neutralDensity` | Same section, `Ar` | Direct |
| `analysis.ionFluxRaw` | `[ION FLUX AT THE SHEATH EDGE] Ar+ (#/cm^2sec)` | Direct; retain separately from converted metric |
| `analysis.metastableFluxRaw` | `[RADICAL FLUX AT THE SHEATH EDGE] Ar* (#/cm^2sec)` | Direct |
| `analysis.neutralFluxRaw` | Same section, `Ar` | Direct |
| `analysis.finalResidualMax` | Last complete numeric residual row | Maximum absolute value across **all columns after iteration**, including Te |
| `analysis.strictConvergence` | Above maximum and INI `[Option].conv` | `finalResidualMax <= conv`; distinct from engine completion |
| `analysis.hasDistribution` | Bias condition plus required output validation | Baseline Bias-on true, Bias-off false; a missing required Bias-on output is an incomplete Run, not a successful Bias-off substitute |

Fixture `units` strings are exactly: pressure `mTorr`, sourcePower/biasPower `W`, ionFlux `10¹⁸ m⁻²s⁻¹`, meanIonEnergy/iedWidth `eV`. Analysis graph units remain raw: current `statampere/cm^2`, potential `V`, density `#/cm^3`, distance `cm`, phase `rf cycle`, residual `a.u.`, angle `degrees`.


| Graph / fixture destination | Raw filename, metadata, row grammar | Reconstruction and fixture shape |
| --- | --- | --- |
| IED: `iedDistribution` | `0d_result/output/IED/Ar+.txt`; `type=IEDs`, `gtype=1D`, `nx=N`; rows `[energy,intensity]` | M=161; objects `{energy,intensity}` in selected source order. Width uses full raw rows before sampling. |
| IAD: `analysis.iad` | `0d_result/output/IAD/Ar+.txt`; `type=IADs`, `gtype=1D`, `nx=N`; `[angle,intensity]` | M=101; **pairs** `[angle,intensity]`, not IED-style objects. Baseline raw N=201. |
| IEAD: `analysis.iead` | `0d_result/output/IEAD/Ar+.txt`; `type=IEAD`, `gtype=2D`, `nx=angleCount`, `ny=energyCount`; `[angle,energy,intensity]` | Angle-major blocks; for numeric row ordinal k, angle index `k/ny`, energy index `k%ny`. Select angle axis M=31 and energy axis M=61 separately with shared index rule. `angles` = selected angle coordinates, `energies` = selected energy coordinates; `values` flat length 31×61 in **angle→energy** order, i.e. `values[a*energies.length+e]`. `sourceShape=[nx,ny]`; `angleRange=[first raw angle,last raw angle]`. Baseline nx=201, ny varies 171..2136. |
| Current: `analysis.current` | `0d_result/output/CUR/J0h_h.txt`; `type=Current_density`, `gtype=1D`, `nx=N`; `[phase,currentDensity]` | M=121; `{points:[[phase,value],...],phaseRange:[first raw phase,last raw phase],sourceCount:N}`. No cgs-to-SI conversion. |
| Potential: `analysis.potential` | `0d_result/output/POT/pot.txt`; `type=Pot`, `gtype=1D`, `nx=N`; `[phase,potential]` | Same shape and M=121 as current. No offset normalization or amplitude derivation. |
| Density: `analysis.density` | `0d_result/output/DEN/Ar+.txt`; `type=DENSITY`, `gtype=2D`, `nx=phaseCount`, `ny=distanceCount`; `[phase,distance,density]` | Phase-major blocks; ordinal k gives phase index `k/ny`, distance index `k%ny`. Select 41 phase indices; **retain all original 31 distance rows**. `rows` = `[[phase,[distance0,...],[density0,...]],...]` (41 triples, each with two arrays of length 31). `sourceShape=[nx,ny]`. Do not transpose or flatten into IEAD schema. |
| Residual: `analysis.residualTrace` | `0d_result/log/residual.log`; `type=residual`, `gtype=1D`, `species=E Ar* Ar+ Ar Te`; numeric row `[iteration,E,Ar*,Ar+,Ar,Te]`; no nx header | M=81 numeric rows. For each selected row emit `[iteration,max(abs(species residuals))]`. Final maximum/strict flag use the **last raw row** independently. |


## 파서 및 그래프 규칙

INI는 section/key로 구분하고 첫 `=`에서 나눈다. `rfCycle`의 알려진 U+0001을 보존한다. solver species는 section과 정확한 이름으로 구분한다. 원본 type/gtype/축 단위·선언 shape·유한 수치·행 수를 검증한다. INI/solver/폴더 조건 충돌은 오류다. Java 초기 지원은 Ar/TCP/CW/release 8.8.1이다. 업로드 JS를 실행하지 않는다.

공통 sampling: m=min(N,M), index=roundHalfEven(i*(N−1)/(m−1)); N=1은 0 한 개. 각 좌표는 선택된 원본 행에서 가져오며 보간·정규화·스무딩·정렬은 없다. IED/IAD/IEAD angle/IEAD energy/current/potential/density phase/residual target은 각각 161/101/31/61/121/121/41/81이고 density distance는 전체 원본을 유지한다. sourceShape/phaseRange/angleRange/sourceCount는 원본 계보이며 표시 격자의 크기가 아니다.

IED width는 전체 unsampled intensity 누적 합의 10%,90%에 처음 도달한 에너지 차이며 energy bin weighting/보간이 없다. binary64 차를 `new BigDecimal(difference).round(new MathContext(8, HALF_EVEN)).doubleValue()`로 처리한다. `BigDecimal.valueOf`를 사용하지 않는다. 최종 residual max와 strict threshold는 마지막 **원본** 행의 iteration 뒤 모든 column 절대값 기준이며 표시 trace의 마지막 선택 행으로 추론하지 않는다.

기본 조건/scalar에 INI와 solver.log가 필요하다. 성공 검색에는 output.log의 전체 `INFO: Finished!` 줄, 마지막 유효 residual 행, Bias-on의 모든 그래프가 필요하다. Bias-off []/null은 정상 부재이며 실패가 아니다. 누락은 INCOMPLETE, 손상/nonfinite/모순은 PARSE_FAILED이고 concrete path/line/field를 남긴다. 실패한 새 버전은 마지막 성공 검색 버전을 덮어쓰지 않는다.

sourceFiles 고정 순서: setting.ini, solver.log, residual.log, Bias-on만 IED/IAD/IEAD/CUR/POT/DEN. 이름은 실제 basename(`0d_setting.ini`, `solver.log`, `residual.log`, `Ar+.txt`, `Ar+.txt`, `Ar+.txt`, `J0h_h.txt`, `pot.txt`, `Ar+.txt`)이고 type은 SETTING/LOG/LOG/IED/IAD/IEAD/CURRENT/POTENTIAL/DENSITY다. 같은 basename을 합치지 않는다. 전체 ingestion manifest는 별도다. byte/1024 또는 byte/1048576를 BigDecimal HALF_EVEN 소수점 1자리로 표시하며 ASCII space와 KB/MB를 쓴다.

원본 root `source`(string), `sampling`({method:string,interpolated:boolean,note:string}), `levels`({pressure:number[],sourcePower:number[],biasPower:number[]}), `runs`(FullRun 원본 배열, version ID는 import에서 부여)을 외부 패키지에 보존한다. 등록 시각은 원본 파일 mtime나 물리 로그에서 유도하지 않고 import/DB 정책이 소유한다. mock-data.js의 별도 목업은 실제 성공 Run이 아니다.

## 대화·기록·Agent 계약

StateToken 세대/revision은 비음수 정수다. 현재 대화/참조 저장은 전체 token, 기록 저장은 workspaceEpoch를 검증하며 오래된 저장은 409 STALE_CONTEXT다. 턴은 선택된 context RunRef와 answerRunRefs로 불변 버전을 고정한다. answerSnapshot은 원본 intent/status/후보/설명/문구/순서를 보존하는 compact object이며 FullRun/analysis/그래프를 중복 저장하지 않는다. 일시 화면 필터/작성 중 입력은 WorkspaceView에 없다.

REV는 version 필드가 없는 ReviewRecord, EXP는 version=2인 ExperimentRecord다. 원본 targetRunId/comparedRunIds와 snapshots의 runId를 유지하면서 targetRunRef/comparedRunRefs 및 scalar snapshot runVersionId를 추가해 버전을 고정한다. REV의 constraints/goals/evidenceKinds/limitations/runSnapshots, EXP의 question/objectives/overallComment/candidates/objectiveEvaluations, 두 타입의 원래 메타를 모두 보존한다. 새 일반 EXP 입력은 채택 1개, 추가 후보 최대 2개, HOLD/REJECT만 허용한다. ALTERNATIVE/COMPARISON은 과거 호환 읽기에 남는다. Java DecisionRecord는 binding 지정에 따라 하나의 nested record로 운반하며 null EXP 전용 필드/version은 직렬화에서 생략한다. 저장 서비스가 OpenAPI oneOf와 새 입력 유효성을 검증한다.

AgentRequest/Response와 AgentContext의 hydrateFullRun는 RunRef를 사용한다. 현재 후보는 최신 summary, 과거 참조는 version별 FullRun이다. 스냅샷의 유연한 순수 JSON 객체는 원본 검색/목표/설명 구조를 손실 없이 보존하기 위한 경계이며 새로운 수치·가상 Run을 만들 허가가 아니다.

## 외부 기준 패키지

`prototype/`, `raw/`, `tests/`, `manifest.json`을 외부 폴더에 둔다. manifest는 `version:"v12.3.1"`, `files:{relativePath:sha256}`이고 모든 원본 byte를 추적한다. prepare는 `--prototype --raw --tests --output` 명시 루트만 읽고 저장소 안 output, 소스/output 겹침, overwrite, symlink를 거부한다. loader는 원본 JS를 실행하지 않고 필수 파일/전체 inventory/경로/SHA-256을 검증한다. 출력과 원본 각각 hash를 비교해 원본 보존도 확인한다.

```sh
node scripts/reference/prepare.mjs --prototype /external/prototype-source --raw /external/raw-source --tests /external/test-source --output /external/reference/v12.3.1
KPLASMA_REFERENCE_ROOT=/external/reference/v12.3.1 npm run reference:check
node --test scripts/reference/check.test.mjs
```

`loadReference(root: string): Promise<ReferencePackage>`는 root/version/prototypeRoot/rawRoot/testsRoot/manifest를 반환한다. I/O는 async다. `reference:check`는 환경 변수 누락 시 안내와 nonzero exit를 반환한다. 원본 UI·실제 payload·테스트의 실제 기대값·manifest checksum·검증 화면은 저장소에 복사하지 않는다.
