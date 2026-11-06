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
