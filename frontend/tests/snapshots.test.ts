import assert from 'node:assert/strict'
import test from 'node:test'
import { acceptSnapshot, type Session } from '../src/services/api.ts'

test('a late HTTP response must not overwrite newer SSE field values', () => {
  const latest = { id: 'one', sequence: 12, fields: [{ value: 'Quixadá' }] } as Session
  const stale = { id: 'one', sequence: 10, fields: [{ value: 'Fortaleza' }] } as Session
  assert.equal(acceptSnapshot(latest, stale), latest)
  assert.equal(acceptSnapshot(latest, { ...stale, sequence: 13 }).sequence, 13)
})

test('a new session can replace an old session with a higher sequence', () => {
  const old = { id: 'old', sequence: 100 } as Session
  const next = { id: 'new', sequence: 1 } as Session
  assert.equal(acceptSnapshot(old, next), next)
})
