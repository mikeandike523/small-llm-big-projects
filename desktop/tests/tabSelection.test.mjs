import { test } from 'node:test';
import assert from 'node:assert/strict';
import {
  isOverlayId,
  nextActiveAfterClose,
  restoredActiveId,
  toggledOverlay,
} from '../src/shared/tabSelection.ts';

test('closing a middle tab focuses its right neighbour', () => {
  assert.equal(nextActiveAfterClose(['a', 'b', 'c'], 'b'), 'c');
});

test('closing the rightmost tab focuses its left neighbour', () => {
  assert.equal(nextActiveAfterClose(['a', 'b', 'c'], 'c'), 'b');
});

test('closing the only tab leaves no focus tab', () => {
  assert.equal(nextActiveAfterClose(['a'], 'a'), null);
});

test('an unknown id leaves no focus tab', () => {
  assert.equal(nextActiveAfterClose(['a', 'b'], 'zzz'), null);
});

test('an overlay icon toggles its own overlay and replaces another', () => {
  assert.equal(toggledOverlay(null, 'downloads'), 'downloads');
  assert.equal(toggledOverlay('downloads', 'downloads'), null);
  assert.equal(toggledOverlay('health', 'settings'), 'settings');
});

test('overlay ids are validated', () => {
  assert.equal(isOverlayId('health'), true);
  assert.equal(isOverlayId('tab-1'), false);
  assert.equal(isOverlayId(undefined), false);
});

test('restores the focus tab by position, falling back to the first, then none', () => {
  assert.equal(restoredActiveId(1, ['t1', 't2']), 't2');
  assert.equal(restoredActiveId(5, ['t1', 't2']), 't1');
  assert.equal(restoredActiveId(undefined, ['t1']), 't1');
  assert.equal(restoredActiveId(0, []), null);
});
