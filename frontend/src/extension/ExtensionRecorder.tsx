import { useEffect, useState, type ComponentProps } from 'react'
import { AudioRecorder } from '../components/AudioRecorder'

export function ExtensionRecorder({
  tabId,
  disabledReason,
  ...props
}: ComponentProps<typeof AudioRecorder> & { tabId: number; disabledReason: string }) {
  const [authorized, setAuthorized] = useState(false)
  const [opening, setOpening] = useState(false)
  const [error, setError] = useState('')

  useEffect(() => {
    let cancelled = false
    let revision = 0
    const refresh = () => {
      const current = ++revision
      void chrome.storage.local
        .get('microphoneAuthorized')
        .then((value) => {
          if (!cancelled && current === revision) setAuthorized(value.microphoneAuthorized === true)
        })
        .catch(() => {
          if (!cancelled && current === revision)
            setError(
              'Não foi possível consultar a autorização do microfone. Tente abrir a autorização novamente.',
            )
        })
    }
    const changed = (changes: Record<string, { newValue?: unknown }>, area: string) => {
      if (!cancelled && area === 'local' && 'microphoneAuthorized' in changes) {
        revision++
        setAuthorized(changes.microphoneAuthorized.newValue === true)
        setError('')
      }
    }
    // Subscribe before reading so an older read cannot overwrite a new grant.
    chrome.storage.onChanged.addListener(changed)
    refresh()
    window.addEventListener('focus', refresh)
    document.addEventListener('visibilitychange', refresh)
    return () => {
      cancelled = true
      window.removeEventListener('focus', refresh)
      document.removeEventListener('visibilitychange', refresh)
      chrome.storage.onChanged.removeListener(changed)
    }
  }, [])

  function permissionDenied() {
    setAuthorized(false)
    setError(
      'O acesso ao microfone foi bloqueado. Abra a autorização para conferir as permissões do Chrome e do sistema.',
    )
    // Cached confirmation never replaces Chrome's enforcement during capture.
    void chrome.storage.local.set({ microphoneAuthorized: false }).catch(() => {})
  }

  async function openPermission() {
    setOpening(true)
    setError('')
    try {
      await chrome.tabs.create({ url: chrome.runtime.getURL(`microphone.html?tab=${tabId}`) })
    } catch {
      setError(
        'Não foi possível abrir a autorização do microfone. Tente novamente ou envie um arquivo de áudio.',
      )
    } finally {
      setOpening(false)
    }
  }

  return (
    <div className="extension-recorder">
      {authorized ? (
        <AudioRecorder {...props} onPermissionDenied={permissionDenied} />
      ) : (
        <>
          <button
            className="primary"
            type="button"
            disabled={props.disabled || opening}
            onClick={() => void openPermission()}
          >
            {opening ? 'Abrindo autorização…' : 'Ativar microfone'}
          </button>
          <p className="recorder-help">
            Na primeira vez, o Chrome pedirá autorização em uma aba própria. Depois, você grava aqui
            no painel.
          </p>
        </>
      )}
      {props.disabled && (
        <p role="status" className="recorder-help">
          {disabledReason}
        </p>
      )}
      {error && (
        <p role="status" className="recorder-error">
          {error}
        </p>
      )}
    </div>
  )
}
