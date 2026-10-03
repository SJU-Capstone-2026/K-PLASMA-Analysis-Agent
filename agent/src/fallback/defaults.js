// Original units and query defaults; no Run fixtures or generated physical results.
  const units = Object.freeze({
    pressure: 'mTorr',
    sourcePower: 'W',
    biasPower: 'W',
    ionFlux: '10¹⁸ m⁻²s⁻¹',
    meanIonEnergy: 'eV',
    iedWidth: 'eV',
  });

  const balancedQuery = Object.freeze({
    id: 'QUERY-DEMO-001',
    originalText: 'Pressure 8 mTorr 이하에서 Ion Flux 최대화, Mean Ion Energy 120–150 eV, IED Width 최소화',
    analysisType: 'REVERSE',
    processMode: 'GOAL_RECOMMENDATION',
    originalValues: {
      pressure: { operator: 'MAX', value: 8, unit: 'mTorr', label: '8 mTorr 이하' },
      meanIonEnergy: { operator: 'RANGE', min: 120, max: 150, unit: 'eV', label: '120–150 eV' },
    },
    normalizedConditions: { pressureMax: 8, meanIonEnergyMin: 120, meanIonEnergyMax: 150 },
    constraints: [{ metric: 'pressure', operator: 'MAX', value: 8, unit: 'mTorr' }],
    goals: [
      { metric: 'ionFlux', direction: 'MAX', unit: units.ionFlux, label: 'Ion Flux 최대화' },
      { metric: 'meanIonEnergy', direction: 'TARGET_RANGE', min: 120, max: 150, unit: 'eV', label: 'Mean Ion Energy 120–150 eV' },
      { metric: 'iedWidth', direction: 'MIN', unit: 'eV', label: 'IED Width 최소화' },
    ],
    confirmed: false,
    modified: false,
  });

  const queryPresets = Object.freeze([
    { id: 'reverse-balanced', name: '균형 후보 추천', description: 'Flux·Energy·IED Width 균형', query: balancedQuery },
    { id: 'reverse-flux', name: 'Ion Flux 우선', description: 'Ion Flux가 높은 실측 Run 탐색' },
    { id: 'reverse-width', name: '좁은 IED 우선', description: 'IED Width가 좁은 실측 Run 탐색' },
    { id: 'reverse-constraints', name: '조건 일치 조회', description: '목표 없이 조건에 맞는 모든 Run 조회' },
    { id: 'forward-exact', name: '정방향 정확 일치', description: '6 / 450 / 600 조건 조회' },
    { id: 'forward-nearest', name: '정방향 근접 조건', description: '실제 Run이 없는 조건 조회' },
    { id: 'reverse-no-match', name: '완화 제안', description: '일치 Run이 없는 조건' },
    { id: 'catalog-parse', name: '파일 파싱', description: '파일 등록 상태 데모' },
  ]);


export { units, balancedQuery, queryPresets };
