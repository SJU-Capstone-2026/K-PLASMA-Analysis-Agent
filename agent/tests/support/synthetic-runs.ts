import type { FullRun } from '../../src/contracts';
// Artificial values only; these are not physical observations.
export function syntheticRun(biasOn = true): FullRun {
  return {
    runId: 'SYNTHETIC', runVersionId: '00000000-0000-4000-8000-000000000001',
    pressure: 3, sourcePower: 11, biasPower: biasOn ? 7 : 0,
    metrics: { ionFlux: 13, meanIonEnergy: 17, iedWidth: biasOn ? 2 : null },
    units: { pressure: 'mTorr', sourcePower: 'W', biasPower: 'W', ionFlux: '10¹⁸ m⁻²s⁻¹', meanIonEnergy: 'eV', iedWidth: 'eV' },
    convergenceStatus: 'CONVERGED', qualityStatus: 'VERIFIED', catalogStatus: 'READY',
    registeredAt: '2000-01-01T00:00:00Z', presentationScore: 1, note: 'Artificial contract fixture',
    sourceFiles: [{ name: 'artificial.ini', type: 'SETTING', size: '1.0 KB', status: 'PARSED', path: 'artificial/artificial.ini' }],
    iedDistribution: biasOn ? [{ energy: 1, intensity: 2 }] : [],
    analysis: {
      hasDistribution: biasOn, strictConvergence: false, finalResidualMax: 0.5,
      electronTemperature: 2, ionTemperature: 3, gasTemperature: 4, absorbedPower: 5,
      alpha: 6, plasmaResistance: 7, plasmaReactance: 8, dcOffset: biasOn ? -1 : null,
      peakToPeak: biasOn ? 2 : null, currentDensityPeak: 9, electronDensity: 19,
      ionDensity: 10, metastableDensity: 11, neutralDensity: 12, ionFluxRaw: 13,
      metastableFluxRaw: 14, neutralFluxRaw: 15, residualTrace: [[1, 0.5]],
      iad: biasOn ? [[1, 2]] : null,
      iead: biasOn ? { angles: [1], energies: [2], values: [3], sourceShape: [1, 1], angleRange: [1, 1] } : null,
      current: biasOn ? { points: [[1, 2]], phaseRange: [1, 1], sourceCount: 1 } : null,
      potential: biasOn ? { points: [[1, 2]], phaseRange: [1, 1], sourceCount: 1 } : null,
      density: biasOn ? { rows: [[1, [2], [3]]], sourceShape: [1, 1] } : null,
    },
  };
}
