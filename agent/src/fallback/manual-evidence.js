// v12.3.1: preserved pure implementation; only IIFE/module boundaries changed.


const entries = Object.freeze([
  Object.freeze({
    id: 'output-solver-summary',
    manual: '260324_SJU_K-PLASMA(0D)_OUTPUT_MANUAL.pdf',
    page: 5,
    topic: 'solver.log 결과 항목',
    summary: 'solver.log에서 전자 온도, 종 밀도, 이온 플럭스와 평균 이온 에너지를 확인할 수 있습니다.',
    coverage: 'OUTPUT_DEFINITION_ONLY',
    supportsCausality: false,
  }),
  Object.freeze({
    id: 'output-parameter-history',
    manual: '260324_SJU_K-PLASMA(0D)_OUTPUT_MANUAL.pdf',
    page: 6,
    topic: 'parameter.log 반복 계산 이력',
    summary: 'parameter.log는 계산 중 iteration별 종 밀도와 전자·가스 온도 정보를 저장합니다.',
    coverage: 'OUTPUT_DEFINITION_ONLY',
    supportsCausality: false,
  }),
  Object.freeze({
    id: 'output-distribution-files',
    manual: '260324_SJU_K-PLASMA(0D)_OUTPUT_MANUAL.pdf',
    page: 3,
    topic: '분포·파형 출력 파일',
    summary: 'output 폴더에 IAD, IEAD, IED, Potential, Current, 온도, 플럭스와 평균 에너지 결과가 저장됩니다.',
    coverage: 'OUTPUT_DEFINITION_ONLY',
    supportsCausality: false,
  }),
  Object.freeze({
    id: 'output-residual-history',
    manual: '260324_SJU_K-PLASMA(0D)_OUTPUT_MANUAL.pdf',
    page: 7,
    topic: 'residual.log 수렴 근거',
    summary: 'residual.log는 iteration별 종 밀도와 전자 온도 등 계산 파라미터의 잔차를 저장합니다.',
    coverage: 'QUALITY_EVIDENCE',
    supportsCausality: false,
  }),
]);

export { entries };
