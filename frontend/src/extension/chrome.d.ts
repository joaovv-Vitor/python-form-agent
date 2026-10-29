declare const chrome: {
  runtime: {
    id: string
    getURL(path: string): string
    sendMessage(message: object): Promise<unknown>
    onMessage: {
      addListener(
        listener: (message: { source?: string; kind?: string }, sender: { id?: string }) => void,
      ): void
      removeListener(
        listener: (message: { source?: string; kind?: string }, sender: { id?: string }) => void,
      ): void
    }
  }
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
    update(id: number, properties: { active: boolean }): Promise<unknown>
    getCurrent(): Promise<{ id?: number } | undefined>
    remove(id: number): Promise<void>
  }
  scripting: {
    executeScript(options: { target: { tabId: number }; files: string[] }): Promise<unknown>
  }
  storage: {
    local: {
      get(key: string): Promise<{ microphoneAuthorized?: boolean }>
      set(values: { microphoneAuthorized: boolean }): Promise<void>
    }
    onChanged: {
      addListener(
        listener: (changes: Record<string, { newValue?: unknown }>, area: string) => void,
      ): void
      removeListener(
        listener: (changes: Record<string, { newValue?: unknown }>, area: string) => void,
      ): void
    }
    session: {
      get(key: string): Promise<{ connection?: { server: string } }>
      set(values: Record<string, unknown>): Promise<void>
    }
  }
}
