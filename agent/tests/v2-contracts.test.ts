import { expect, test } from 'vitest';
import * as contracts from '../src/contracts/index.js';

test('rejects an old v1 schema 3 answer and a discriminator-only v2 object', () => {
  const guard = Reflect.get(contracts, 'isGraphV2AnswerSnapshot');
  expect(guard).toBeTypeOf('function');
  expect(guard({ implementationId: 'v1', graphVersion: 'v1', schemaVersion: 3 })).toBe(false);
  expect(guard({ implementationId: 'v2', graphVersion: 'v2', schemaVersion: 1 })).toBe(false);
});

test('accepts the shared artificial v2 snapshot', async () => {
  const { default: fixture } = await import('./support/v2/contracts.json');
  expect(contracts.isGraphV2AnswerSnapshot(fixture.general_answer)).toBe(true);
});

test.each(['v2', 'v3', 'v2_localLLM'])('recognizes %s without weakening the strict v2 guard', async version => {
  const { default: fixture } = await import('./support/v2/contracts.json');
  const snapshot = {...fixture.general_answer, implementationId: version, graphVersion: version};
  const guard = Reflect.get(contracts, 'isCompositeAnswerSnapshot');
  expect(guard).toBeTypeOf('function');
  expect(guard(snapshot)).toBe(true);
  expect(contracts.isGraphV2AnswerSnapshot(snapshot)).toBe(version === 'v2');
  expect(guard({...snapshot, graphVersion: version === 'v3' ? 'v2' : 'v3'})).toBe(false);
  expect(guard({...snapshot, implementationId: 'v1', graphVersion: 'v1'})).toBe(false);
  expect(guard({...snapshot, budget: {...snapshot.budget, model_requests_used: 14}})).toBe(false);
});
