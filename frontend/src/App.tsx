import { useEffect, useRef, useState, type FormEvent } from 'react'
import { AudioRecorder } from './components/AudioRecorder'
import {
  ApiError,
  acceptSnapshot,
  json,
  labels,
  request,
  type DemoForm,
  type Field,
  type Session,
} from './services/api'

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
  showValidation,
}: {
  field: Field
  busy: boolean
  highlighted: boolean
  showValidation: boolean
}) {
  const id = `field-${field.reference}`
  const invalid = showValidation && field.valid === false
  return (
    <div
      className={`field ${['checkbox', 'radio'].includes(field.type) ? 'checkbox-field' : ''} ${invalid ? 'invalid' : ''} ${highlighted ? 'highlighted' : ''}`}
    >
      {['checkbox', 'radio'].includes(field.type) ? (
        <>
          <input id={id} type={field.type} checked={Boolean(field.value)} disabled />
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
          ) : field.type === 'textarea' ? (
            <textarea
              id={id}
              readOnly
              value={String(field.value ?? '')}
              rows={4}
              placeholder="Aguardando informação"
            />
          ) : (
            <input
              id={id}
              type={
                [
                  'email',
                  'tel',
                  'date',
                  'number',
                  'url',
                  'time',
                  'datetime-local',
                  'month',
                  'week',
                ].includes(field.type)
                  ? field.type
                  : 'text'
              }
              readOnly
              value={String(field.value ?? '')}
              placeholder="Aguardando informação"
            />
          )}
        </>
      )}
      {invalid && (
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
  const [recording, setRecording] = useState(false)
  const [connection, setConnection] = useState('Conectando')
  const [file, setFile] = useState<File | null>(null)
  const [audioUrl, setAudioUrl] = useState('')
  const [text, setText] = useState('')
  const [confirm, setConfirm] = useState(false)
  const [maxBytes, setMaxBytes] = useState(25 * 1024 * 1024)
  const [maxSeconds, setMaxSeconds] = useState(120)
  const [forms, setForms] = useState<DemoForm[]>([])
  const [targetUrl, setTargetUrl] = useState(
    new URL('/forms/cadastro', window.location.origin).href,
  )
  const log = useRef<HTMLDivElement>(null)
  const dialog = useRef<HTMLDialogElement>(null)
  const mounted = useRef(true)
  const sessionEnded = terminal.has(session?.state ?? '')

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
      if (mounted.current) {
        update(current)
        setTargetUrl(new URL(current.form_url, window.location.origin).href)
      }
    } catch (e) {
      if (mounted.current) setError((e as Error).message)
    } finally {
      if (mounted.current) setWorking(false)
    }
  }

  useEffect(() => {
    mounted.current = true
    void connect()
    void request<DemoForm[]>('/forms')
      .then(setForms)
      .catch(() => {})
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
    if (!session || sessionEnded) return
    const sessionId = session.id
    let source: EventSource | undefined
    let timer: ReturnType<typeof setTimeout> | undefined
    let disposed = false
    const controller = new AbortController()

    function stop() {
      disposed = true
      source?.close()
      clearTimeout(timer)
      controller.abort()
    }

    function receive(value: Session) {
      if (disposed) return
      update(value)
      if (terminal.has(value.state)) {
        stop()
        setConfirm(false)
      }
    }

    async function recover() {
      try {
        const current = await request<Session>(`/sessions/${sessionId}`, {
          signal: controller.signal,
        })
        receive(current)
        if (!disposed) timer = setTimeout(openStream, 3000)
      } catch (e) {
        if (disposed) return
        if (e instanceof ApiError && e.status === 404) {
          stop()
          setConfirm(false)
          setSession((current) =>
            current?.id === sessionId
              ? {
                  ...current,
                  state: 'expired',
                  question: '',
                  can_message: false,
                  can_correct_audio: false,
                  can_complete: false,
                  can_submit: false,
                }
              : current,
          )
          setError('Sua sessão expirou ou foi encerrada. Inicie uma nova sessão para continuar.')
        } else {
          timer = setTimeout(() => void recover(), 3000)
        }
      }
    }

    function openStream() {
      if (disposed) return
      const stream = new EventSource(`/api/sessions/${sessionId}/events`)
      source = stream
      stream.onopen = () => {
        if (!disposed) setConnection('Conectado')
      }
      stream.addEventListener('session', (event) => {
        if (disposed) return
        try {
          receive(JSON.parse(event.data).state as Session)
          setConnection('Conectado')
        } catch {
          setError('Não foi possível atualizar o estado da sessão.')
        }
      })
      stream.onerror = () => {
        if (disposed || source !== stream) return
        stream.onerror = null
        stream.close()
        setConnection('Reconectando…')
        void recover()
      }
    }

    openStream()
    return stop
  }, [session?.id, sessionEnded])

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
    if (!session || working || recording) return
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

  async function loadTarget(event: FormEvent) {
    event.preventDefault()
    if (working || recording) return
    setWorking(true)
    setError('')
    try {
      if (session && !terminal.has(session.state)) {
        update(await request<Session>(`/sessions/${session.id}`, { method: 'DELETE' }))
        let closed = false
        for (let attempt = 0; attempt < 200; attempt += 1) {
          const current = await request<Session>(`/sessions/${session.id}`)
          if (!mounted.current) return
          update(current)
          if (terminal.has(current.state)) {
            closed = true
            break
          }
          await new Promise((resolve) => setTimeout(resolve, 200))
        }
        if (!closed)
          throw new Error('A sessão anterior ainda está encerrando. Aguarde e tente novamente.')
      }
      const next = await request<Session>('/sessions', json({ url: targetUrl.trim() }))
      if (!mounted.current) return
      setFile(null)
      setText('')
      setConfirm(false)
      update(next)
      setTargetUrl(new URL(next.form_url, window.location.origin).href)
    } catch (e) {
      if (mounted.current) setError((e as Error).message)
    } finally {
      if (mounted.current) setWorking(false)
    }
  }

  const state = session?.state ?? 'preparing'
  const finished = terminal.has(state)
  const busy = active.has(state)
  const showValidation = session?.phase === 'clarification' || session?.phase === 'review'
  const canUpload = session?.state === 'ready' || session?.can_correct_audio
  const canChooseTarget =
    !working && !recording && (!session || ['ready', 'closed', 'expired', 'error'].includes(state))
  const selectedForm = forms.find((form) => form.url === targetUrl)?.id ?? 'custom'
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
          <a href="/extension/setup" className="version-tag">
            Extensão Chrome
          </a>
          <span className="version-tag">Formulários por voz</span>
          {session && !finished && (
            <button
              className="button secondary"
              disabled={working || recording || state === 'closing'}
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
            <p>Consulte os campos, grave ou envie um áudio e acompanhe o preenchimento.</p>
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

        <section className="target-card" aria-label="Escolher formulário de destino">
          <div className="target-heading">
            <div>
              <span className="eyebrow">FORMULÁRIO DE DESTINO</span>
              <p>Escolha um exemplo ou informe uma URL.</p>
            </div>
            {session?.form_url && (
              <a href={session.form_url} target="_blank" rel="noreferrer">
                Ver formulário original ↗
              </a>
            )}
          </div>
          <form className="target-controls" onSubmit={loadTarget}>
            <div>
              <label htmlFor="demo-form">Formulários de demonstração</label>
              <select
                id="demo-form"
                value={selectedForm}
                disabled={!canChooseTarget}
                onChange={(event) => {
                  const form = forms.find((item) => item.id === event.target.value)
                  setTargetUrl(form?.url ?? '')
                }}
              >
                {forms.map((form, index) => (
                  <option key={form.id} value={form.id}>
                    {index + 1}. {form.name}
                    {index === 0 ? ' — formulário original' : ''}
                  </option>
                ))}
                <option value="custom">Outro formulário por URL</option>
              </select>
            </div>
            <div className="target-url">
              <label htmlFor="form-url">URL do formulário</label>
              <input
                id="form-url"
                type="url"
                required
                maxLength={2048}
                value={targetUrl}
                disabled={!canChooseTarget}
                placeholder="https://exemplo.com/formulario"
                onChange={(event) => setTargetUrl(event.target.value)}
              />
            </div>
            <button className="button primary" disabled={!canChooseTarget || !targetUrl.trim()}>
              Abrir formulário
            </button>
          </form>
          <p className="target-help">
            {canChooseTarget
              ? 'O Cadastro é o primeiro exemplo e mantém o formulário que você já utiliza.'
              : 'Encerre a sessão atual para escolher outro formulário.'}
          </p>
        </section>

        <div className="workspace">
          <section className="browser" aria-label="Visualização sincronizada do formulário">
            <div className="browser-bar">
              <span className="dots" aria-hidden="true">
                ● ● ●
              </span>
              <span>{session?.form_name ?? 'Formulário'}</span>
              <small>{session && !finished ? connection : 'Sessão encerrada'}</small>
            </div>
            <div className="form-page">
              <div className="form-card">
                <div className="form-title">
                  <span className="form-logo">{session?.form_name.charAt(0) ?? 'F'}</span>
                  <div>
                    <h2>{session?.form_name ?? 'Formulário'}</h2>
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
                        showValidation={showValidation}
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
                    : session?.is_demo
                      ? 'Você poderá revisar e corrigir seus dados antes de confirmar o envio simulado.'
                      : 'Confira os campos encontrados na página e revise os valores preenchidos.'}
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
                    Diga seus dados olhando os campos ao lado. Use o microfone ou selecione um
                    arquivo de áudio.
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

                {canUpload && (
                  <section className="audio-section" aria-labelledby="audio-title">
                    <h3 id="audio-title">
                      {state === 'ready'
                        ? 'Gravar ou enviar áudio'
                        : session.phase === 'clarification'
                          ? 'Responder por áudio'
                          : 'Corrigir campo por áudio'}
                    </h3>
                    {state !== 'ready' && (
                      <p className="instructions" id="audio-correction-help">
                        {session.phase === 'clarification'
                          ? 'Grave ou envie um áudio respondendo à pergunta do assistente. Os dados já preenchidos são mantidos.'
                          : 'Grave ou envie um áudio dizendo qual campo deseja corrigir e o novo valor. Ex.: “Corrija minha cidade para Quixadá”. Os outros campos são mantidos.'}
                      </p>
                    )}
                    <AudioRecorder
                      key={session.id}
                      disabled={working}
                      maxSeconds={maxSeconds}
                      maxBytes={maxBytes}
                      onRecorded={setFile}
                      onBusyChange={setRecording}
                      onError={setError}
                    />
                    <div className="audio-divider">ou envie um arquivo</div>
                    <form className="upload" onSubmit={upload}>
                      <label
                        className="file-picker"
                        htmlFor="audio-file"
                        aria-disabled={working || recording}
                      >
                        <span className="upload-symbol" aria-hidden="true">
                          ↑
                        </span>
                        <strong>
                          {file
                            ? file.name
                            : state === 'ready'
                              ? 'Selecionar arquivo de áudio'
                              : session?.phase === 'clarification'
                                ? 'Selecionar áudio de resposta'
                                : 'Selecionar áudio de correção'}
                        </strong>
                        <small>
                          WAV, MP3, MP4, M4A, FLAC, WebM ou OGG · até{' '}
                          {Math.round(maxBytes / 1024 / 1024)} MiB · {maxSeconds} segundos
                        </small>
                      </label>
                      <input
                        id="audio-file"
                        type="file"
                        accept=".wav,.mp3,.mp4,.m4a,.flac,.webm,.ogg"
                        aria-describedby={state === 'ready' ? undefined : 'audio-correction-help'}
                        disabled={working || recording}
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
                              disabled={working || recording}
                              onClick={() => setFile(null)}
                            >
                              Remover
                            </button>
                          </div>
                          {audioUrl && (
                            <audio
                              controls
                              src={audioUrl}
                              preload="metadata"
                              aria-label="Prévia do áudio"
                            />
                          )}
                        </>
                      )}
                      <button
                        className="button primary full"
                        disabled={!file || working || recording}
                      >
                        {working
                          ? 'Enviando…'
                          : state === 'ready'
                            ? 'Preencher com áudio'
                            : session?.phase === 'clarification'
                              ? 'Enviar resposta por áudio'
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
                        disabled={working || recording}
                      />
                      <button
                        className="button primary full"
                        disabled={!text.trim() || working || recording}
                      >
                        Enviar mensagem
                      </button>
                    </form>
                  )}
                  {session.can_message && (
                    <button
                      className="text-button"
                      disabled={working || recording}
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
                    disabled={working || recording}
                    onClick={() => void action('/review/complete')}
                  >
                    Concluir revisão
                  </button>
                )}
                {state === 'review_complete' && session.submission_supported && (
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
                {state === 'review_complete' && !session.submission_supported && (
                  <div className="pending">
                    Revisão concluída. O envio automático não está habilitado para este endereço.
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
          Formulários HTML · microfone ou arquivo de áudio · alterações de um campo por pedido
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
