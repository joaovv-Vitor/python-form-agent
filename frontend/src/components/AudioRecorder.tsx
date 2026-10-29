import { useEffect, useRef, useState } from 'react'

type Capture = {
  recorder: MediaRecorder
  stream: MediaStream
  timeout?: ReturnType<typeof setTimeout>
  clock?: ReturnType<typeof setInterval>
}

function release(capture: Capture | null) {
  if (!capture) return
  clearTimeout(capture.timeout)
  clearInterval(capture.clock)
  capture.recorder.ondataavailable = null
  capture.recorder.onstop = null
  capture.recorder.onerror = null
  try {
    if (capture.recorder.state !== 'inactive') capture.recorder.stop()
  } finally {
    capture.stream.getTracks().forEach((track) => track.stop())
  }
}

function duration(seconds: number) {
  const whole = Math.floor(seconds)
  return `${Math.floor(whole / 60)
    .toString()
    .padStart(2, '0')}:${(whole % 60).toString().padStart(2, '0')}`
}

export function AudioRecorder({
  disabled,
  maxSeconds,
  maxBytes,
  onRecorded,
  onBusyChange,
  onError,
  onPermissionDenied,
}: {
  disabled: boolean
  maxSeconds: number
  maxBytes: number
  onRecorded: (file: File) => void
  onBusyChange: (busy: boolean) => void
  onError: (message: string) => void
  onPermissionDenied?: () => void
}) {
  const [phase, setPhase] = useState<'idle' | 'requesting' | 'recording' | 'stopping'>('idle')
  const [elapsed, setElapsed] = useState(0)
  const [recorderError, setRecorderError] = useState('')
  const capture = useRef<Capture | null>(null)
  const generation = useRef(0)
  const supported =
    typeof navigator.mediaDevices?.getUserMedia === 'function' &&
    typeof MediaRecorder !== 'undefined'

  function reportError(message: string) {
    setRecorderError(message)
    onError(message)
  }

  useEffect(() => {
    return () => {
      generation.current += 1
      release(capture.current)
      capture.current = null
      onBusyChange(false)
    }
  }, [onBusyChange])

  function cancel() {
    generation.current += 1
    release(capture.current)
    capture.current = null
    setPhase('idle')
    onBusyChange(false)
  }

  function stop() {
    const recorder = capture.current?.recorder
    if (!recorder || recorder.state === 'inactive') return
    setPhase('stopping')
    recorder.stop()
  }

  async function start() {
    if (disabled || phase !== 'idle' || !supported) return
    const current = ++generation.current
    let stream: MediaStream | undefined
    setPhase('requesting')
    setElapsed(0)
    setRecorderError('')
    onBusyChange(true)
    onError('')
    try {
      stream = await navigator.mediaDevices.getUserMedia({ audio: true })
      if (generation.current !== current) {
        stream.getTracks().forEach((track) => track.stop())
        return
      }
      const mimeType = [
        'audio/webm;codecs=opus',
        'audio/mp4',
        'audio/ogg;codecs=opus',
        'audio/webm',
      ].find((type) => MediaRecorder.isTypeSupported(type))
      const recorder = new MediaRecorder(stream, mimeType ? { mimeType } : undefined)
      const recording: Capture = { recorder, stream }
      capture.current = recording
      const chunks: Blob[] = []
      let bytes = 0
      recorder.ondataavailable = (event) => {
        if (generation.current !== current || !event.data.size) return
        bytes += event.data.size
        if (bytes > maxBytes) {
          cancel()
          reportError('A gravação excedeu o tamanho permitido. Grave um áudio mais curto.')
          return
        }
        chunks.push(event.data)
      }
      recorder.onerror = () => {
        if (generation.current !== current) return
        cancel()
        reportError('Não foi possível gravar o áudio. Tente novamente ou envie um arquivo.')
      }
      recorder.onstop = () => {
        if (generation.current !== current) return
        const type = recorder.mimeType || chunks[0]?.type || mimeType || ''
        const extension = type.includes('webm')
          ? 'webm'
          : type.includes('mp4')
            ? 'm4a'
            : type.includes('ogg')
              ? 'ogg'
              : null
        release(recording)
        capture.current = null
        setPhase('idle')
        onBusyChange(false)
        if (!bytes || !extension) {
          reportError('Não foi possível preparar a gravação. Tente novamente ou envie um arquivo.')
          return
        }
        const stamp = new Date().toISOString().replace(/[:.]/g, '-')
        onRecorded(new File(chunks, `gravacao-${stamp}.${extension}`, { type }))
      }
      recorder.start(250)
      setPhase('recording')
      const started = performance.now()
      recording.clock = setInterval(() => setElapsed((performance.now() - started) / 1000), 250)
      // Leave room for the encoder's final frames within the server's duration limit.
      const limit = maxSeconds - Math.min(0.5, maxSeconds / 10)
      recording.timeout = setTimeout(stop, limit * 1000)
    } catch (error) {
      stream?.getTracks().forEach((track) => track.stop())
      if (generation.current !== current) return
      cancel()
      const name = error instanceof DOMException ? error.name : ''
      if (name === 'NotAllowedError' || name === 'SecurityError') onPermissionDenied?.()
      reportError(
        name === 'NotAllowedError' || name === 'SecurityError'
          ? 'Permita o acesso ao microfone no navegador ou envie um arquivo de áudio.'
          : name === 'NotFoundError'
            ? 'Nenhum microfone foi encontrado. Conecte um microfone ou envie um arquivo.'
            : name === 'NotReadableError'
              ? 'O microfone está indisponível. Confira as permissões do sistema e se outro programa está usando o dispositivo.'
              : 'Não foi possível acessar o microfone. Confira se ele está disponível ou envie um arquivo.',
      )
    }
  }

  return (
    <div className={`recorder ${phase === 'recording' ? 'is-recording' : ''}`}>
      {phase === 'idle' ? (
        <button
          type="button"
          className="button secondary full"
          disabled={disabled || !supported}
          onClick={() => void start()}
        >
          <svg
            width="18"
            height="20"
            viewBox="0 0 24 24"
            fill="none"
            stroke="currentColor"
            strokeWidth="1.8"
            aria-hidden="true"
          >
            <rect x="9" y="2" width="6" height="12" rx="3" />
            <path d="M5 10v2a7 7 0 0 0 14 0v-2M12 19v3m-4 0h8" />
          </svg>
          Usar microfone
        </button>
      ) : (
        <>
          <div className="recorder-status" role="status">
            {phase === 'recording' && <span className="recording-dot" aria-hidden="true" />}
            {phase === 'requesting'
              ? 'Aguardando acesso ao microfone…'
              : phase === 'stopping'
                ? 'Preparando gravação…'
                : `Gravando · ${duration(elapsed)} / ${duration(maxSeconds)}`}
          </div>
          <div className="recorder-actions">
            {phase === 'recording' && (
              <button type="button" className="button primary" onClick={stop}>
                Parar gravação
              </button>
            )}
            <button type="button" className="text-button" onClick={cancel}>
              Cancelar gravação
            </button>
          </div>
        </>
      )}
      <p className="recorder-help">
        {!supported
          ? 'O microfone precisa de um navegador compatível em HTTPS ou localhost. Você pode enviar um arquivo abaixo.'
          : 'Grave, pare e ouça antes de enviar. A gravação termina no limite de tempo.'}
      </p>
      {recorderError && (
        <p className="recorder-error" role="status">
          {recorderError}
        </p>
      )}
    </div>
  )
}
