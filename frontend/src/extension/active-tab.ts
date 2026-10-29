type Tab = { id?: number; url?: string }
type PageReply = {
  success?: boolean
  error?: string
  url?: string
  document_id?: string
}

type TabBrowser = {
  tabs: {
    query(query: { active: boolean; lastFocusedWindow: boolean }): Promise<Tab[]>
    sendMessage(id: number, message: object): Promise<PageReply>
  }
  scripting: {
    executeScript(options: { target: { tabId: number }; files: string[] }): Promise<unknown>
  }
}

const authorize =
  'Abra a aba do formulário e clique no ícone VozForm na barra de extensões do Chrome para autorizar o acesso. Depois clique em “Usar formulário desta aba”.'

export async function prepareActiveForm(browser: TabBrowser) {
  const [tab] = await browser.tabs.query({ active: true, lastFocusedWindow: true })
  if (typeof tab?.id !== 'number' || !Number.isInteger(tab.id) || tab.id < 0) {
    throw new Error('Não foi possível identificar a aba ativa. ' + authorize)
  }
  // URL is sensitive metadata and may be absent even though the tab ID exists.
  // Let Chrome enforce scripting permission; inspect the actual page afterwards.
  if (tab.url && !/^https?:\/\//.test(tab.url)) {
    throw new Error(
      'Abra o site do formulário em uma aba HTTP ou HTTPS. Páginas internas do Chrome não podem ser usadas.',
    )
  }
  try {
    await browser.scripting.executeScript({
      target: { tabId: tab.id },
      files: ['content-script.js'],
    })
  } catch {
    throw new Error('O Chrome não liberou o acesso a esta aba. ' + authorize)
  }
  let page: PageReply
  try {
    page = await browser.tabs.sendMessage(tab.id, { source: 'vozform', kind: 'prepare' })
  } catch {
    throw new Error('A aba foi fechada ou recarregada. ' + authorize)
  }
  if (!page?.success) throw new Error(page?.error || 'Não foi possível ler os campos desta aba.')
  if (!page.url || !/^https?:\/\//.test(page.url) || !page.document_id) {
    throw new Error('Não foi possível confirmar o formulário desta página. ' + authorize)
  }
  return { tabId: tab.id, url: page.url, documentId: page.document_id }
}
