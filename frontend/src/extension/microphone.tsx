import { useEffect, useRef, useState } from 'react'
import { createRoot } from 'react-dom/client'
import './panel.css'

function MicrophonePermission() {
  const [state, setState] = useState<'idle' | 'requesting' | 'allowed' | 'error'>('idle')
  const [error, setError] = useState('')
  const mounted = useRef(true)
  useEffect(() => {
    mounted.current = true
    return () => {
      mounted.current = false
    }
  }, [])

  async function returnToForm() {
    const value = new URLSearchParams(location.search).get('tab')
    const tabId = value && /^\d+$/.test(value) ? Number(value) : null
    if (tabId === null) return
    try {
      await chrome.tabs.update(tabId, { active: true })
      // Keep this document alive for Chrome's "Allow this time" permission.
      // Its stream has already been stopped; retaining the tab is not recording.
    } catch {
      /* The original tab may already be closed; leave the success page visible. */
    }
  }

  async function allow() {
    setState('requesting')
    setError('')
    let expired = false
    const request = navigator.mediaDevices.getUserMedia({ audio: true })
    // Permission prompts cannot be aborted; always stop a late stream as well.
    void request
      .then((stream) => {
        if (expired || !mounted.current) stream.getTracks().forEach((track) => track.stop())
      })
      .catch(() => {})
    let timer: ReturnType<typeof setTimeout> | undefined
    try {
      const stream = await Promise.race([
        request,
        new Promise<never>((_, reject) => {
          timer = setTimeout(
            () =>
              reject(
                new DOMException(
                  'Confirme a permissão no Chrome e tente novamente.',
                  'PermissionTimeout',
                ),
              ),
            30000,
          )
        }),
      ])
      stream.getTracks().forEach((track) => track.stop())
      if (!mounted.current) return
      // Persist before closing this page: the panel may be hidden or reloading,
      // and a runtime message or PermissionStatus event may never reach it.
      await chrome.storage.local.set({ microphoneAuthorized: true })
      setState('allowed')
      await returnToForm()
    } catch (failure) {
      if (!mounted.current) return
      const name = failure instanceof DOMException ? failure.name : ''
      setError(
        name === 'NotFoundError'
          ? 'Nenhum microfone foi encontrado. Conecte um dispositivo e tente novamente.'
          : name === 'NotReadableError'
            ? 'Não foi possível abrir o dispositivo. Confira as permissões do sistema e feche outros programas que estejam usando o microfone.'
            : name === 'PermissionTimeout'
              ? 'Confirme a permissão no Chrome. Depois clique em Permitir microfone novamente.'
              : 'O Chrome ou o sistema bloqueou o microfone. Permita o acesso nas configurações de microfone do navegador e do sistema e tente novamente.',
      )
      setState('error')
    } finally {
      expired = true
      clearTimeout(timer)
    }
  }

  return (
    <main className="panel permission-page">
      <header>
        <span className="logo">V</span>
        <div>
          <h1>Ativar microfone</h1>
          <p>Uma autorização para o VozForm</p>
        </div>
      </header>
      <section className="card">
        <h2>{state === 'allowed' ? 'Microfone autorizado' : 'Permita o uso do seu microfone'}</h2>
        <p>
          O Chrome precisa mostrar a autorização em uma aba da extensão. Clique abaixo e escolha
          Permitir na solicitação do navegador.
        </p>
        <p>
          Esta etapa apenas verifica o acesso. A gravação começa quando você clicar em Usar
          microfone no painel.
        </p>
        {state === 'allowed' && (
          <p>
            Mantenha esta aba aberta enquanto usa o microfone no painel. Ela não está gravando e
            pode ser fechada quando terminar.
          </p>
        )}
        {error && (
          <div role="alert" className="notice error">
            {error}
          </div>
        )}
        {state === 'allowed' ? (
          <button className="primary" onClick={() => void returnToForm()}>
            Voltar ao formulário
          </button>
        ) : (
          <button
            className="primary"
            disabled={state === 'requesting'}
            onClick={() => void allow()}
          >
            {state === 'requesting' ? 'Confirme a permissão no Chrome…' : 'Permitir microfone'}
          </button>
        )}
        <p role="status">
          {state === 'requesting'
            ? 'Aguardando a resposta do navegador. Confira também a solicitação do sistema operacional.'
            : state === 'allowed'
              ? 'Você já pode gravar pelo painel do VozForm.'
              : 'Você também pode continuar usando o envio de arquivos de áudio.'}
        </p>
      </section>
    </main>
  )
}

createRoot(document.getElementById('root')!).render(<MicrophonePermission />)
