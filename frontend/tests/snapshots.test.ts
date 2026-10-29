import assert from 'node:assert/strict'
import test from 'node:test'
import { ApiError, acceptSnapshot, request, type Session } from '../src/services/api.ts'

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

test('a late response cannot reactivate an expired or closed session', () => {
  for (const state of ['expired', 'closed']) {
    const ended = { id: 'one', state, sequence: 12 } as Session
    const late = { id: 'one', state: 'reviewing', sequence: 13 } as Session
    assert.equal(acceptSnapshot(ended, late), ended)
    assert.equal(acceptSnapshot(ended, { ...late, id: 'new' }).id, 'new')
  }
})

test('request preserves HTTP status to distinguish missing sessions from temporary failures', async (t) => {
  t.mock.method(globalThis, 'fetch', async () =>
    Response.json({ detail: 'Sessão não encontrada ou expirada.' }, { status: 404 }),
  )
  await assert.rejects(request('/sessions/missing'), (error: unknown) => {
    assert.ok(error instanceof ApiError)
    assert.equal(error.status, 404)
    assert.equal(error.message, 'Sessão não encontrada ou expirada.')
    return true
  })
})
