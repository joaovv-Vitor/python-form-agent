import { useEffect, useRef, useState, type FormEvent } from 'react'
import { acceptSnapshot, json, labels, request, type Field, type Session } from './services/api'

const terminal = new Set(['closed', 'expired'])
const active = new Set([
  'preparing',
  'validating',
  'queued',
  'transcribing',
  'filling',
  'verifying',
  'correcting',
  'sending',
  'closing',
])

function Wave() {
  return (
    <svg
      width="22"
      height="22"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      aria-hidden="true"
    >
      <path d="M3 12h2m2-4v8m3-11v14m3-10v6m3-9v12m3-7v2" />
    </svg>
  )
}

function FormField({
  field,
  busy,
  highlighted,
}: {
  field: Field
  busy: boolean
  highlighted: boolean
}) {
  const id = `field-${field.reference}`
  return (
    <div
      className={`field ${field.type === 'checkbox' ? 'checkbox-field' : ''} ${field.valid === false ? 'invalid' : ''} ${highlighted ? 'highlighted' : ''}`}
    >
      {field.type === 'checkbox' ? (
        <>
          <input id={id} type="checkbox" checked={Boolean(field.value)} disabled />
          <label htmlFor={id}>{field.label}</label>
        </>
      ) : (
        <>
          <label htmlFor={id}>
            {field.label}
            {field.required && <span aria-label=" obrigatório"> *</span>}
          </label>
          {field.type === 'select' ? (
            <select id={id} value={String(field.value ?? '')} disabled>
              {field.options?.map((o) => (
                <option key={o.value} value={o.value}>
                  {o.label}
                </option>
              ))}
            </select>
          ) : (
            <input
              id={id}
              type={
                ['email', 'tel', 'date', 'number', 'url'].includes(field.type) ? field.type : 'text'
              }
              readOnly
              value={String(field.value ?? '')}
              placeholder="Aguardando informação"
            />
          )}
        </>
      )}
      {field.valid === false && (
        <small className="field-error">{field.validation_message || 'Confira este valor.'}</small>
      )}
      {busy && field.value && field.type !== 'checkbox' && (
        <small className="field-note">Valor recebido · aguardando conferência final</small>
      )}
    </div>
  )
}

export default function App() {
  const [session, setSession] = useState<Session | null>(null)
  const [error, setError] = useState('')
  const [working, setWorking] = useState(false)
  const [connection, setConnection] = useState('Conectando')
  const [file, setFile] = useState<File | null>(null)
  const [audioUrl, setAudioUrl] = useState('')
  const [text, setText] = useState('')
  const [confirm, setConfirm] = useState(false)
  const [maxBytes, setMaxBytes] = useState(25 * 1024 * 1024)
  const [maxSeconds, setMaxSeconds] = useState(120)
  const log = useRef<HTMLDivElement>(null)
  const dialog = useRef<HTMLDialogElement>(null)
  const mounted = useRef(true)

  function update(value: Session) {
    setSession((current) => acceptSnapshot(current, value))
  }

  async function connect() {
    setWorking(true)
    setError('')
    try {
      let current: Session
      try {
        current = await request<Session>('/session')
      } catch {
        current = await request<Session>('/sessions', { method: 'POST' })
      }
      if (mounted.current) update(current)
    } catch (e) {
      if (mounted.current) setError((e as Error).message)
    } finally {
      if (mounted.current) setWorking(false)
    }
  }

  useEffect(() => {
    mounted.current = true
    void connect()
    void request<{ max_upload_bytes: number; max_audio_seconds: number }>('/health')
      .then((v) => {
        setMaxBytes(v.max_upload_bytes)
        setMaxSeconds(v.max_audio_seconds)
      })
      .catch(() => {})
    return () => {
      mounted.current = false
    }
  }, [])

  useEffect(() => {
    if (!session || terminal.has(session.state)) return
    const source = new EventSource(`/api/sessions/${session.id}/events`)
    source.onopen = () => setConnection('Conectado')
    source.addEventListener('session', (event) => {
      try {
        const value = JSON.parse(event.data).state as Session
        update(value)
        setConnection('Conectado')
        if (terminal.has(value.state)) source.close()
      } catch {
        setError('Não foi possível atualizar o estado da sessão.')
      }
    })
    source.onerror = () => setConnection('Reconectando…')
    return () => source.close()
  }, [session?.id])

  useEffect(() => {
    if (!file) {
      setAudioUrl('')
      return
    }
    const url = URL.createObjectURL(file)
    setAudioUrl(url)
    return () => URL.revokeObjectURL(url)
  }, [file])

  useEffect(() => {
    log.current?.scrollTo({ top: log.current.scrollHeight, behavior: 'smooth' })
  }, [session?.messages.length])
  useEffect(() => {
    if (confirm) dialog.current?.showModal()
    else dialog.current?.close()
  }, [confirm])

  async function action(path: string, options: RequestInit = { method: 'POST' }) {
    if (!session || working) return
    setWorking(true)
    setError('')
    try {
      const result = await request<Session>(`/sessions/${session.id}${path}`, options)
      update(result)
      return result
    } catch (e) {
      setError((e as Error).message)
    } finally {
      setWorking(false)
    }
  }

  async function upload(event: FormEvent) {
    event.preventDefault()
    if (!file) return
    if (file.size > maxBytes) {
      setError(`Envie um arquivo de até ${Math.round(maxBytes / 1024 / 1024)} MiB.`)
      return
    }
    const body = new FormData()
    body.append('file', file)
    const result = await action(session?.state === 'ready' ? '/audio' : '/corrections/audio', {
      method: 'POST',
      body,
    })
    if (result) setFile(null)
  }

  async function send(event: FormEvent) {
    event.preventDefault()
    if (!text.trim()) return
    const result = await action('/messages', json({ text: text.trim() }))
    if (result) setText('')
  }

  const state = session?.state ?? 'preparing'
  const finished = terminal.has(state)
  const busy = active.has(state)
  const canUpload = session?.state === 'ready' || session?.can_correct_audio
  const issues = session?.issues.filter((i) => i.code !== 'SUBMISSION_BLOCKED') ?? []

  return (
    <div className="app">
      <header className="header">
        <a className="brand" href="/" aria-label="VozForm, início">
          <span className="brand-symbol">
            <Wave />
          </span>
          VozForm
        </a>
        <div className="header-actions">
          <span className="version-tag">Primeira versão · formulário padrão</span>
          {session && !finished && (
            <button
              className="button secondary"
              disabled={working || state === 'closing'}
              onClick={() => void action('', { method: 'DELETE' })}
            >
              Encerrar sessão
            </button>
          )}
        </div>
      </header>
      <main>
        <section className="heading">
          <div>
            <span className="eyebrow">PREENCHIMENTO ASSISTIDO POR ÁUDIO</span>
            <h1>Seus dados, com a sua voz.</h1>
            <p>Consulte os campos, envie uma gravação e acompanhe o preenchimento.</p>
          </div>
          <span className={`status ${busy ? 'running' : ''}`} role="status">
            <i />
            {labels[state]}
          </span>
        </section>

        {error && (
          <div className="error-banner" role="alert">
            <span>{error}</span>
            <button
              className="text-button"
              onClick={() => setError('')}
              aria-label="Fechar mensagem de erro"
            >
              Fechar
            </button>
          </div>
        )}

        <div className="workspace">
          <section className="browser" aria-label="Visualização sincronizada do formulário">
            <div className="browser-bar">
              <span className="dots" aria-hidden="true">
                ● ● ●
              </span>
              <span>Cadastro · formulário padrão</span>
              <small>{session && !finished ? connection : 'Sessão encerrada'}</small>
            </div>
            <div className="form-page">
              <div className="form-card">
                <div className="form-title">
                  <span className="form-logo">C</span>
                  <div>
                    <h2>Cadastro</h2>
                    <p>Confira os campos e acompanhe suas informações.</p>
                  </div>
                </div>
                {session?.fields.length ? (
                  <div className="fields">
                    {session.fields.map((field) => (
                      <FormField
                        key={field.reference}
                        field={field}
                        busy={busy}
                        highlighted={session.active_field === field.reference}
                      />
                    ))}
                  </div>
                ) : (
                  <div className="empty-form">
                    <span className="spinner" />
                    {error
                      ? 'Aguardando uma sessão disponível.'
                      : 'Preparando os campos do formulário…'}
                  </div>
                )}
                <div className="form-footnote">
                  {state === 'sent'
                    ? 'Envio simulado confirmado pelo formulário.'
                    : 'Você poderá revisar e corrigir seus dados antes de confirmar o envio.'}
                </div>
              </div>
            </div>
          </section>

          <aside className="voice-panel" aria-label="Áudio e conversa com o assistente">
            <div className="panel-heading">
              <span className="eyebrow">SUA SESSÃO</span>
              <h2>
                {session?.question
                  ? 'Precisamos da sua resposta'
                  : state === 'ready'
                    ? 'Envie seu áudio'
                    : labels[state]}
              </h2>
            </div>

            {(!session || finished) && (
              <div className="intro-card">
                <p>
                  {finished
                    ? 'Os recursos desta sessão foram liberados. Você pode começar novamente.'
                    : 'Estamos preparando o formulário padrão para você.'}
                </p>
                <button
                  className="button primary full"
                  disabled={working}
                  onClick={() => {
                    setFile(null)
                    setText('')
                    void connect()
                  }}
                >
                  {working ? 'Conectando…' : 'Iniciar nova sessão'}
                </button>
              </div>
            )}

            {session && !finished && (
              <>
                {busy && (
                  <div className="activity" role="status">
                    <span className="spinner" />
                    <span>
                      {working ? 'Enviando solicitação…' : labels[state]}
                      <small>Você pode continuar consultando os campos.</small>
                    </span>
                  </div>
                )}
                {state === 'ready' && (
                  <p className="instructions">
                    Grave seus dados olhando os campos ao lado. Selecione o arquivo quando estiver
                    pronto.
                  </p>
                )}
                {issues.length > 0 && (
                  <div className="pending" role="status">
                    <strong>Confira as pendências</strong>
                    <ul>
                      {issues.map((issue, i) => (
                        <li key={i}>{issue.message}</li>
                      ))}
                    </ul>
                  </div>
                )}
                {session.submission_denied && (
                  <div className="pending">
                    O áudio contém uma instrução para não enviar. O envio está bloqueado.
                  </div>
                )}

                {(state === 'ready' || session.can_correct_audio) && (
                  <section className="audio-section" aria-labelledby="audio-title">
                    <h3 id="audio-title">
                      {state === 'ready' ? 'Arquivo de áudio' : 'Corrigir campo por áudio'}
                    </h3>
                    {state !== 'ready' && (
                      <p className="instructions" id="audio-correction-help">
                        Envie uma gravação dizendo qual campo deseja corrigir e o novo valor. Ex.:
                        “Corrija minha cidade para Quixadá”. Os outros campos são mantidos.
                      </p>
                    )}
                    <form className="upload" onSubmit={upload}>
                      <label className="file-picker" htmlFor="audio-file">
                        <span className="upload-symbol" aria-hidden="true">
                          ↑
                        </span>
                        <strong>
                          {file
                            ? file.name
                            : state === 'ready'
                              ? 'Selecionar arquivo de áudio'
                              : 'Selecionar áudio de correção'}
                        </strong>
                        <small>
                          WAV, MP3, MP4, M4A ou FLAC · até {Math.round(maxBytes / 1024 / 1024)} MiB
                          · {maxSeconds} segundos
                        </small>
                      </label>
                      <input
                        id="audio-file"
                        type="file"
                        accept=".wav,.mp3,.mp4,.m4a,.flac"
                        aria-describedby={state === 'ready' ? undefined : 'audio-correction-help'}
                        disabled={working}
                        onChange={(e) => {
                          setFile(e.target.files?.[0] ?? null)
                          e.target.value = ''
                          setError('')
                        }}
                      />
                      {file && (
                        <>
                          <div className="file-info">
                            <span>{(file.size / 1024).toFixed(0)} KiB</span>
                            <button
                              className="text-button"
                              type="button"
                              onClick={() => setFile(null)}
                            >
                              Remover
                            </button>
                          </div>
                          {audioUrl && <audio controls src={audioUrl} preload="metadata" />}
                        </>
                      )}
                      <button className="button primary full" disabled={!file || working}>
                        {working
                          ? 'Enviando…'
                          : state === 'ready'
                            ? 'Preencher com áudio'
                            : 'Enviar áudio de correção'}
                      </button>
                    </form>
                  </section>
                )}

                <section className="conversation" aria-label="Mensagens da sessão">
                  <h3>Conversa com o assistente</h3>
                  <div
                    className="messages"
                    ref={log}
                    role="log"
                    aria-live="polite"
                    aria-relevant="additions"
                  >
                    {session.messages.map((message, i) => (
                      <div key={`${i}-${message.time}`} className={`message ${message.who}`}>
                        <small>{message.who === 'user' ? 'Você' : 'Assistente'}</small>
                        <p>{message.text}</p>
                      </div>
                    ))}
                  </div>
                  {session.can_message && (
                    <form className="composer" onSubmit={send}>
                      <label htmlFor="correction">
                        {session.question ? 'Sua resposta' : 'Peça uma correção por texto'}
                      </label>
                      <textarea
                        id="correction"
                        value={text}
                        onChange={(e) => setText(e.target.value)}
                        maxLength={4000}
                        placeholder={
                          session.question
                            ? 'Digite a informação solicitada'
                            : 'Ex.: Corrija minha cidade para Quixadá'
                        }
                        disabled={working}
                      />
                      <button className="button primary full" disabled={!text.trim() || working}>
                        Enviar mensagem
                      </button>
                    </form>
                  )}
                  {session.can_message && (
                    <button
                      className="text-button"
                      disabled={working}
                      onClick={() => void action('/review/skip')}
                    >
                      Descartar pedido pendente
                    </button>
                  )}
                </section>

                {session.transcriptions.length > 0 && (
                  <details className="transcriptions">
                    <summary>Consultar transcrições ({session.transcriptions.length})</summary>
                    {session.transcriptions.map((t, i) => (
                      <div key={i}>
                        <strong>
                          {t.kind === 'initial' ? 'Áudio inicial' : 'Áudio de correção'}
                        </strong>
                        <p>{t.text}</p>
                      </div>
                    ))}
                  </details>
                )}

                {session.can_complete && (
                  <button
                    className="button primary full finish"
                    disabled={working}
                    onClick={() => void action('/review/complete')}
                  >
                    Concluir revisão
                  </button>
                )}
                {state === 'review_complete' && (
                  <div className="final-action">
                    <p>
                      Revise os valores antes de confirmar. Este formulário realiza um envio de
                      demonstração.
                    </p>
                    <button
                      className="button primary full"
                      disabled={!session.can_submit || working}
                      onClick={() => setConfirm(true)}
                    >
                      Revisar e confirmar envio
                    </button>
                  </div>
                )}
                {state === 'sent' && (
                  <div className="success-banner" role="status">
                    Envio simulado confirmado. Encerre a sessão para liberar o servidor.
                  </div>
                )}
              </>
            )}
          </aside>
        </div>
        <p className="scope-note">
          V1 · formulário padrão · arquivos de áudio · alterações de um campo por pedido
        </p>
      </main>
      <dialog
        ref={dialog}
        onCancel={() => setConfirm(false)}
        onClose={() => setConfirm(false)}
        aria-labelledby="confirm-title"
      >
        <div className="confirmation">
          <span className="eyebrow">CONFIRMAÇÃO SEPARADA</span>
          <h2 id="confirm-title">Confirmar envio simulado?</h2>
          <p>Estes são os valores conferidos nesta sessão:</p>
          <dl>
            {session?.fields.map((f) => (
              <div key={f.reference}>
                <dt>{f.label}</dt>
                <dd>
                  {f.type === 'checkbox'
                    ? f.value
                      ? 'Sim'
                      : 'Não'
                    : (f.options?.find((o) => o.value === f.value)?.label ??
                      String(f.value || 'Não informado'))}
                </dd>
              </div>
            ))}
          </dl>
          <div className="dialog-actions">
            <button className="button secondary" onClick={() => setConfirm(false)}>
              Voltar
            </button>
            <button
              className="button primary"
              disabled={working || !session?.can_submit}
              onClick={async () => {
                setConfirm(false)
                await action(
                  '/submit',
                  json({ confirmation: 'ENVIAR', revision: session?.revision }),
                )
              }}
            >
              Confirmar envio
            </button>
          </div>
        </div>
      </dialog>
      <footer>VozForm · Você acompanha, revisa e confirma.</footer>
    </div>
  )
}
