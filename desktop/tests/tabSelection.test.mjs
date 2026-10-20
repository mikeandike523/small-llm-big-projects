import { test } from 'node:test';
import assert from 'node:assert/strict';
import { nextActiveAfterClose, restoredActiveId } from '../src/shared/tabSelection.ts';

test('closing a middle tab activates its right neighbour', () => {
  assert.equal(nextActiveAfterClose(['a', 'b', 'c'], 'b'), 'c');
});

test('closing the rightmost tab activates its left neighbour', () => {
  assert.equal(nextActiveAfterClose(['a', 'b', 'c'], 'c'), 'b');
});

test('closing the only tab leaves nothing active', () => {
  assert.equal(nextActiveAfterClose(['a'], 'a'), null);
});

test('an unknown id leaves nothing active', () => {
  assert.equal(nextActiveAfterClose(['a', 'b'], 'zzz'), null);
});

const BUILT_INS = ['health', 'settings', 'downloads'];

test('restores a built-in page by id', () => {
  assert.equal(restoredActiveId({ builtInId: 'downloads' }, ['t1'], BUILT_INS), 'downloads');
});

test('restores a strip tab by position', () => {
  assert.equal(restoredActiveId({ stripIndex: 1 }, ['t1', 't2'], BUILT_INS), 't2');
});

test('falls back to the first strip tab, then to nothing', () => {
  assert.equal(restoredActiveId({ stripIndex: 5 }, ['t1', 't2'], BUILT_INS), 't1');
  assert.equal(restoredActiveId({ builtInId: 'gone' }, ['t1'], BUILT_INS), 't1');
  assert.equal(restoredActiveId(undefined, [], BUILT_INS), null);
  assert.equal(restoredActiveId(null, [], BUILT_INS), null);
});
