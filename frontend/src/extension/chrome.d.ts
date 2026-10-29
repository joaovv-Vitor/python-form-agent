declare const chrome: {
  runtime: { id: string }
  tabs: {
    query(query: {
      active: boolean
      lastFocusedWindow: boolean
    }): Promise<{ id?: number; url?: string; title?: string }[]>
    sendMessage(
      tabId: number,
      message: object,
    ): Promise<{
      success?: boolean
      error?: string
      url?: string
      document_id?: string
      [key: string]: unknown
    }>
    create(properties: { url: string }): Promise<unknown>
  }
  scripting: {
    executeScript(options: { target: { tabId: number }; files: string[] }): Promise<unknown>
  }
  storage: {
    session: {
      get(key: string): Promise<{ connection?: { server: string; token: string } }>
      set(values: Record<string, unknown>): Promise<void>
    }
  }
}
