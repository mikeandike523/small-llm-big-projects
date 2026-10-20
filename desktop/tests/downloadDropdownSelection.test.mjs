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

test('opens with the new download on top, then other pending newest first', () => {
  const ids = selectDropdownIds(
    [pending('p1', 10), finalized('a', 1), pending('new', 5), pending('p2', 20)],
    'new',
  );
  assert.deepEqual(ids, ['new', 'p2', 'p1']);
});

test('finished history never fills the dropdown', () => {
  assert.deepEqual(selectDropdownIds([finalized('a', 1), finalized('b', 2), pending('new', 3)], 'new'), ['new']);
});

test('a download that failed at once still opens the dropdown', () => {
  const failed = finalized('new', 4, { finalizeReason: 'failed' });
  assert.deepEqual(selectDropdownIds([failed, pending('p1', 1)], 'new'), ['new', 'p1']);
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
