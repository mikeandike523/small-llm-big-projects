import { test } from 'node:test';
import assert from 'node:assert/strict';
import {
  addToOpenDropdown,
  pendingProgress,
  selectDropdownIds,
} from '../src/shared/downloadDropdownSelection.ts';

function pending(id, startedAt, receivedBytes = 0, totalBytes = 0) {
  return { id, filename: id, savePath: id, receivedBytes, totalBytes, bytesPerSecond: 0, startedAt, state: 'pending' };
}

function finalized(id, finalizedAt, extra = {}) {
  return {
    id,
    filename: id,
    savePath: id,
    receivedBytes: 0,
    totalBytes: 0,
    bytesPerSecond: 0,
    startedAt: finalizedAt - 1,
    state: 'finalized',
    finalizeReason: 'done',
    finalizedAt,
    ...extra,
  };
}

test('no pending: newest three undismissed finalized', () => {
  const ids = selectDropdownIds([
    finalized('a', 1),
    finalized('b', 2),
    finalized('c', 3, { dismissedFromDropdown: true }),
    finalized('d', 4, { finalizeReason: 'failed' }),
    finalized('e', 5, { finalizeReason: 'canceled' }),
  ]);
  assert.deepEqual(ids, ['e', 'd', 'b']);
});

test('pending first (newest first), finalized fill the remainder', () => {
  const ids = selectDropdownIds([pending('p1', 10), finalized('a', 1), finalized('b', 2), pending('p2', 20)]);
  assert.deepEqual(ids, ['p2', 'p1', 'b']);
});

test('pending are never capped and leave no finalized slots', () => {
  const downloads = [1, 2, 3, 4, 5].map((n) => pending(`p${n}`, n));
  downloads.push(finalized('a', 100));
  assert.deepEqual(selectDropdownIds(downloads), ['p5', 'p4', 'p3', 'p2', 'p1']);
});

test('empty history', () => {
  assert.deepEqual(selectDropdownIds([]), []);
});

test('new download while open goes on top, without duplicates', () => {
  assert.deepEqual(addToOpenDropdown(['a', 'b'], 'n'), ['n', 'a', 'b']);
  assert.deepEqual(addToOpenDropdown(['n', 'a'], 'n'), ['n', 'a']);
});

test('pending progress mean ignores unknown sizes and finalized', () => {
  const progress = pendingProgress([
    pending('a', 1, 50, 100),
    pending('b', 2, 100, 100),
    pending('c', 3, 10, 0),
    finalized('d', 4),
  ]);
  assert.equal(progress.count, 3);
  assert.equal(progress.meanPercent, 75);
});

test('pending progress with no known sizes is null', () => {
  assert.deepEqual(pendingProgress([pending('a', 1, 5, 0)]), { count: 1, meanPercent: null });
  assert.deepEqual(pendingProgress([]), { count: 0, meanPercent: null });
});
