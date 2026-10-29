import assert from 'node:assert/strict'
import test from 'node:test'
import { prepareActiveForm } from '../src/extension/active-tab.ts'

function browser(tab: { id?: number; url?: string } = { id: 12 }) {
  const calls: unknown[] = []
  return {
    calls,
    tabs: {
      async query(options: object) {
        calls.push(options)
        return [tab]
      },
      async sendMessage(id: number, message: object) {
        calls.push({ id, message })
        return { success: true, url: 'https://example.com/contact', document_id: 'document' }
      },
    },
    scripting: {
      async executeScript(options: object) {
        calls.push(options)
      },
    },
  }
}

test('a tab without exposed URL can still be inspected through permitted scripting', async () => {
  const chrome = browser()
  assert.deepEqual(await prepareActiveForm(chrome), {
    tabId: 12,
    url: 'https://example.com/contact',
    documentId: 'document',
  })
  assert.deepEqual(chrome.calls[0], { active: true, lastFocusedWindow: true })
  assert.deepEqual(chrome.calls[1], { target: { tabId: 12 }, files: ['content-script.js'] })
})

test('missing scripting permission explains the toolbar action needed to grant access', async () => {
  const chrome = browser()
  chrome.scripting.executeScript = async () => {
    throw new Error('Cannot access contents of url')
  }
  await assert.rejects(prepareActiveForm(chrome), /Chrome não liberou.*ícone VozForm/)
  assert.equal(chrome.calls.length, 1)
})

test('a restricted page is rejected before injection and an invalid tab is distinct', async () => {
  const internal = browser({ id: 12, url: 'chrome://extensions' })
  await assert.rejects(prepareActiveForm(internal), /Páginas internas do Chrome/)
  assert.equal(internal.calls.length, 1)
  await assert.rejects(prepareActiveForm(browser({})), /identificar a aba ativa/)
  assert.equal((await prepareActiveForm(browser({ id: 0 }))).tabId, 0)
})

test('the target is captured before later asynchronous work can change the active tab', async () => {
  const chrome = browser({ id: 12, url: 'https://example.com/contact' })
  chrome.scripting.executeScript = async () => {
    chrome.tabs.query = async () => [{ id: 99 }]
  }
  const page = await prepareActiveForm(chrome)
  assert.equal(page.tabId, 12)
  assert.deepEqual(chrome.calls[1], { id: 12, message: { source: 'vozform', kind: 'prepare' } })
})

test('a page that cannot be read preserves its specific form error', async () => {
  const chrome = browser()
  chrome.tabs.sendMessage = async () => ({
    success: false,
    error: 'Use um único formulário.',
    url: '',
    document_id: '',
  })
  await assert.rejects(prepareActiveForm(chrome), /Use um único formulário/)
})
