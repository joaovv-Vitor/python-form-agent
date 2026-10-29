import { useEffect, useRef, useState, type FormEvent } from 'react'
import { AudioRecorder } from '../components/AudioRecorder'
import { ApiError, acceptSnapshot, labels, type Session } from '../services/api'
import { prepareActiveForm } from './active-tab'

type Connection = { server: string; token: string }
type Binding = { id: string; tabId: number; connection: Connection }
type Command = {
  id: string
  name: string
  arguments: Record<string, string>
  document_id: string
  url: string
}
const ended = new Set(['closed', 'expired'])

function serverUrl(value: string) {
  const url = new URL(value)
  if (
    url.protocol !== 'http:' ||
    !['127.0.0.1', 'localhost'].includes(url.hostname) ||
    url.username ||
    url.password ||
    url.pathname !== '/' ||
    url.search ||
    url.hash
  ) {
    throw new Error('Use o endereço local do servidor, por exemplo http://127.0.0.1:8000.')
  }
  return url.origin
}

async function api<T>(connection: Connection, path: string, options: RequestInit = {}): Promise<T> {
  const response = await fetch(`${connection.server}/api${path}`, {
    ...options,
    credentials: 'omit',
    signal: options.signal ?? AbortSignal.timeout(10000),
    headers: {
      Authorization: `Bearer ${connection.token}`,
      'X-VozForm-Client': chrome.runtime.id,
      ...options.headers,
    },
  })
  const data = await response.json()
  if (!response.ok)
    throw new ApiError(
      typeof data.detail === 'string' ? data.detail : 'Não foi possível concluir a solicitação.',
      response.status,
    )
  return data as T
}

const json = (value: object): RequestInit => ({
  method: 'POST',
  headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify(value),
})

export default function ExtensionApp() {
  const [server, setServer] = useState('http://127.0.0.1:8000')
  const [token, setToken] = useState('')
  const [session, setSession] = useState<Session | null>(null)
  const [binding, setBinding] = useState<Binding | null>(null)
  const [error, setError] = useState('')
  const [connectionStatus, setConnectionStatus] = useState('')
  const [connectionError, setConnectionError] = useState('')
  const [working, setWorking] = useState(false)
  const [recording, setRecording] = useState(false)
  const [file, setFile] = useState<File | null>(null)
  const [preview, setPreview] = useState('')
  const [text, setText] = useState('')
  const [limits, setLimits] = useState({
    max_upload_bytes: 25 * 1024 * 1024,
    max_audio_seconds: 120,
  })
  const mounted = useRef(true)
  const uploadInput = useRef<HTMLInputElement>(null)

  useEffect(() => {
    mounted.current = true
    void chrome.storage.session.get('connection').then(({ connection }) => {
      if (mounted.current && connection) {
        setServer(connection.server)
        setToken(connection.token)
      }
    })
    return () => {
      mounted.current = false
    }
  }, [])

  useEffect(() => {
    if (!file) {
      if (uploadInput.current) uploadInput.current.value = ''
      setPreview('')
      return
    }
    const url = URL.createObjectURL(file)
    setPreview(url)
    return () => URL.revokeObjectURL(url)
  }, [file])

  useEffect(() => {
    if (!binding) return
    let cancelled = false
    let timer: ReturnType<typeof setTimeout>
    const abort = new AbortController()
    async function poll() {
      let delay = 250
      try {
        const value = await api<{ session: Session; command: Command | null }>(
          binding!.connection,
          `/extension/sessions/${binding!.id}/poll`,
          { signal: AbortSignal.any([abort.signal, AbortSignal.timeout(10000)]) },
        )
        if (cancelled) return
        setConnectionStatus('Conectado')
        setConnectionError('')
        setSession((current) => acceptSnapshot(current, value.session))
        if (ended.has(value.session.state)) {
          setBinding(null)
          return
        }
        if (value.command) {
          let result
          try {
            result = await chrome.tabs.sendMessage(binding!.tabId, {
              source: 'vozform',
              kind: 'command',
              command: value.command,
            })
            if (!result) throw new Error('A aba não respondeu.')
          } catch {
            await api(binding!.connection, `/sessions/${binding!.id}`, { method: 'DELETE' })
            if (!cancelled) {
              setError(
                'A aba foi fechada ou recarregada. A sessão foi encerrada; selecione o formulário novamente.',
              )
              setBinding(null)
            }
            return
          }
          if (cancelled) return
          await api(binding!.connection, `/extension/sessions/${binding!.id}/results`, {
            ...json({ command_id: value.command.id, result }),
            signal: AbortSignal.any([abort.signal, AbortSignal.timeout(10000)]),
          })
          delay = 30
        }
      } catch (failure) {
        if (cancelled) return
        setConnectionStatus('Sem conexão')
        setConnectionError(
          `${(failure as Error).message} Confira se o servidor continua ligado e se o código de conexão está atualizado.`,
        )
        if (failure instanceof ApiError && [401, 404].includes(failure.status)) {
          setBinding(null)
          setSession(null)
          setFile(null)
          return
        }
        delay = 2000
      }
      if (!cancelled) timer = setTimeout(poll, delay)
    }
    void poll()
    const close = () => {
      cancelled = true
      clearTimeout(timer)
      abort.abort()
      void api(binding.connection, `/sessions/${binding.id}`, {
        method: 'DELETE',
        keepalive: true,
      }).catch(() => {})
    }
    window.addEventListener('pagehide', close)
    return () => {
      window.removeEventListener('pagehide', close)
      close()
    }
  }, [binding])

  async function attach() {
    setWorking(true)
    setError('')
    setConnectionError('')
    try {
      const connection = { server: serverUrl(server), token: token.trim() }
      if (!connection.token)
        throw new Error('Cole o código da página Conectar extensão do servidor.')
      const page = await prepareActiveForm(chrome)
      const health = await api<typeof limits>(connection, '/health')
      const next = await api<Session>(
        connection,
        '/extension/sessions',
        json({ url: page.url, document_id: page.documentId }),
      )
      if (!mounted.current) {
        await api(connection, `/sessions/${next.id}`, { method: 'DELETE' })
        return
      }
      await chrome.storage.session.set({ connection })
      setLimits(health)
      setSession(next)
      setFile(null)
      setText('')
      setBinding({ id: next.id, tabId: page.tabId, connection })
    } catch (failure) {
      setError((failure as Error).message)
    } finally {
      if (mounted.current) setWorking(false)
    }
  }

  async function action(path: string, options: RequestInit, after?: () => void) {
    if (!binding) return
    setWorking(true)
    setError('')
    try {
      const next = await api<Session>(binding.connection, `/sessions/${binding.id}${path}`, options)
      if (!mounted.current) return
      setSession((current) => acceptSnapshot(current, next))
      after?.()
    } catch (failure) {
      if (mounted.current) setError((failure as Error).message)
    } finally {
      if (mounted.current) setWorking(false)
    }
  }

  function upload() {
    if (!file) return
    if (file.size > limits.max_upload_bytes) {
      setError('O áudio excede o limite de tamanho. Escolha um arquivo menor.')
      return
    }
    const data = new FormData()
    data.append('file', file)
    void action(
      session?.state === 'ready' ? '/audio' : '/corrections/audio',
      { method: 'POST', body: data },
      () => setFile(null),
    )
  }

  function message(event: FormEvent) {
    event.preventDefault()
    if (text.trim()) void action('/messages', json({ text: text.trim() }), () => setText(''))
  }

  const active = Boolean(binding)
  const canAudio = Boolean(
    session && binding && (session.state === 'ready' || session.can_correct_audio),
  )
  const showValidation = session?.phase === 'review' || session?.phase === 'clarification'

  return (
    <main className="panel">
      <header>
        <span className="logo">V</span>
        <div>
          <h1>VozForm</h1>
          <p>Seu formulário, com a sua voz</p>
        </div>
      </header>
      <p className="status" role="status">
        {session ? labels[session.state] || session.state : 'Conecte o servidor e escolha uma aba'}
        {active && connectionStatus ? ` · ${connectionStatus}` : ''}
      </p>
      {(error || connectionError) && (
        <div role="alert" className="notice error">
          {error || connectionError}
        </div>
      )}
      <section aria-label="Conectar servidor" className="card">
        <label htmlFor="server">Servidor local</label>
        <input
          id="server"
          type="url"
          value={server}
          disabled={active || working}
          onChange={(event) => setServer(event.target.value)}
        />
        <label htmlFor="token">Código de conexão</label>
        <input
          id="token"
          type="password"
          autoComplete="off"
          value={token}
          disabled={active || working}
          onChange={(event) => setToken(event.target.value)}
        />
        <button
          className="link"
          disabled={active || working}
          onClick={() => {
            try {
              void chrome.tabs.create({ url: `${serverUrl(server)}/extension/setup` })
            } catch (failure) {
              setError((failure as Error).message)
            }
          }}
        >
          Obter código no servidor
        </button>
        {!active && (
          <button className="primary" disabled={working} onClick={() => void attach()}>
            {working ? 'Conectando…' : 'Usar formulário desta aba'}
          </button>
        )}
        <small>
          Mantenha o servidor Python ligado. A página escolhida receberá os valores diretamente.
        </small>
      </section>

      {active && session && (
        <>
          <section className="card" aria-label="Formulário conectado">
            <h2>Formulário conectado</h2>
            <p className="destination">{session.form_url}</p>
            <p>Esta sessão permanece vinculada à aba escolhida, mesmo se você trocar de aba.</p>
            <button
              disabled={working || recording}
              onClick={() =>
                void action('', { method: 'DELETE' }, () => {
                  setBinding(null)
                  setFile(null)
                })
              }
            >
              Encerrar sessão
            </button>
          </section>
          <section className="card" aria-label="Preencher por áudio">
            <h2>{session.state === 'ready' ? 'Preencher por áudio' : 'Corrigir por áudio'}</h2>
            <AudioRecorder
              disabled={!canAudio || working}
              maxSeconds={limits.max_audio_seconds}
              maxBytes={limits.max_upload_bytes}
              onRecorded={setFile}
              onBusyChange={setRecording}
              onError={setError}
            />
            <label htmlFor="audio-file">Ou envie um arquivo de áudio</label>
            <input
              id="audio-file"
              ref={uploadInput}
              type="file"
              accept=".wav,.mp3,.mp4,.m4a,.flac,.webm,.ogg"
              disabled={!canAudio || working || recording}
              onChange={(event) => setFile(event.target.files?.[0] || null)}
            />
            <small>
              Até {Math.round(limits.max_upload_bytes / 1024 / 1024)} MiB ·{' '}
              {limits.max_audio_seconds} segundos
            </small>
            {file && (
              <>
                <p className="filename">{file.name}</p>
                <audio controls src={preview} />
              </>
            )}
            <button
              className="primary"
              disabled={!canAudio || !file || working || recording}
              onClick={upload}
            >
              {session.state === 'ready' ? 'Preencher com áudio' : 'Enviar áudio de correção'}
            </button>
          </section>
          {!!session.issues.filter((issue) => issue.code !== 'SUBMISSION_BLOCKED').length && (
            <div className="notice" role="status">
              <strong>Confira as pendências</strong>
              <ul>
                {session.issues
                  .filter((issue) => issue.code !== 'SUBMISSION_BLOCKED')
                  .map((issue, index) => (
                    <li key={index}>{issue.message}</li>
                  ))}
              </ul>
            </div>
          )}
          <section className="card" aria-label="Conversa com o assistente">
            <h2>Conversa com o assistente</h2>
            <div className="messages" role="log" aria-live="polite">
              {session.messages.map((entry, index) => (
                <div key={index}>
                  <strong>{entry.who === 'user' ? 'Você' : 'Assistente'}</strong>
                  <p>{entry.text}</p>
                </div>
              ))}
            </div>
            {session.can_message && (
              <form onSubmit={message}>
                <label htmlFor="message">
                  {session.question ? 'Sua resposta' : 'Peça uma correção por texto'}
                </label>
                <textarea
                  id="message"
                  rows={3}
                  value={text}
                  disabled={working || recording}
                  onChange={(event) => setText(event.target.value)}
                  placeholder="Ex.: Corrija minha cidade para Sobral"
                />
                <button className="primary" disabled={!text.trim() || working || recording}>
                  Enviar mensagem
                </button>
              </form>
            )}
            {session.can_message && (
              <button
                disabled={working || recording}
                onClick={() => void action('/review/skip', json({}))}
              >
                Descartar pedido pendente
              </button>
            )}
            {session.can_complete && (
              <button
                className="primary"
                disabled={working || recording}
                onClick={() => void action('/review/complete', json({}))}
              >
                Concluir revisão
              </button>
            )}
            {session.state === 'review_complete' && (
              <p className="notice">
                Revisão concluída. Confira os valores na página e clique em Enviar no próprio site.
              </p>
            )}
          </section>
          <details className="card">
            <summary>Campos encontrados ({session.fields.length})</summary>
            <dl>
              {session.fields.map((field) => (
                <div key={field.reference}>
                  <dt>
                    {field.label}
                    {field.required ? ' *' : ''}
                  </dt>
                  <dd>
                    {typeof field.value === 'boolean'
                      ? field.value
                        ? 'Marcado'
                        : 'Não marcado'
                      : field.value || 'Aguardando informação'}
                    {showValidation && field.valid === false && (
                      <small className="field-error">
                        {field.validation_message || 'Confira este campo.'}
                      </small>
                    )}
                  </dd>
                </div>
              ))}
            </dl>
          </details>
          {!!session.transcriptions.length && (
            <details className="card">
              <summary>Transcrições ({session.transcriptions.length})</summary>
              {session.transcriptions.map((entry, index) => (
                <p key={index}>{entry.text}</p>
              ))}
            </details>
          )}
        </>
      )}
      <footer>Você revisa e envia no site. A extensão preenche e confere os campos.</footer>
    </main>
  )
}
