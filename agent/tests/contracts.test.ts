import { describe, expect, it } from 'vitest';
import { toRunSummary } from '../src/contracts';
import wire from './support/contract-wire.json';
import { syntheticRun } from './support/synthetic-runs';

describe('Run wire boundary', () => {
  it('keeps version identity and scalar analysis while excluding graph payloads', () => {
    const full = syntheticRun();
    const summary = toRunSummary(full);
    expect(summary.runVersionId).toBe(full.runVersionId);
    expect(summary.analysis.electronDensity).toBe(19);
    expect(summary.analysis).not.toHaveProperty('residualTrace');
    expect(summary.analysis).not.toHaveProperty('density');
    expect(summary).not.toHaveProperty('iedDistribution');
    expect(summary).not.toHaveProperty('sourceFiles');
  });
  it('matches the shared artificial Java wire input for both availability states', () => {
    expect(syntheticRun()).toEqual(wire.on);
    expect(syntheticRun(false)).toEqual(wire.off);
    expect(toRunSummary(syntheticRun())).toEqual(wire.summaryOn);
    expect(toRunSummary(syntheticRun(false))).toEqual(wire.summaryOff);
  });
  it('preserves normal bias-off nulls without substituting zero', () => {
    const full = syntheticRun(false);
    expect(full.metrics.iedWidth).toBeNull();
    expect(toRunSummary(full).analysis.dcOffset).toBeNull();
    expect(full.analysis.density).toBeNull();
    expect(full.iedDistribution).toEqual([]);
  });
});
