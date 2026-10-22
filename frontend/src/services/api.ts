export type Field = {
  reference: string
  label: string
  type: string
  value: string | boolean | null
  options?: { label: string; value: string }[]
  valid: boolean | null
  validation_message: string
  required: boolean
}
export type Session = {
  id: string
  state: string
  revision: number
  sequence: number
  form_name: string
  fields: Field[]
  issues: { code: string; message: string }[]
  question: string
  messages: { who: string; text: string; time: string }[]
  transcriptions: { kind: string; text: string }[]
  corrections: { field: string; previous: unknown; value: unknown; status: string }[]
  can_message: boolean
  can_correct_audio: boolean
  can_complete: boolean
  can_submit: boolean
  submission_denied: boolean
  phase: string
  active_field: string
}

export const labels: Record<string, string> = {
  preparing: 'Preparando formulário',
  ready: 'Pronto para receber seu áudio',
  validating: 'Conferindo arquivo de áudio',
  queued: 'Aguardando processamento',
  transcribing: 'Transcrevendo áudio',
  filling: 'Preenchendo os campos',
  verifying: 'Conferindo valores',
  reviewing: 'Pronto para revisar',
  awaiting_answer: 'Aguardando sua resposta',
  correcting: 'Processando correção',
  review_complete: 'Revisão concluída',
  sending: 'Confirmando envio',
  sent: 'Envio simulado confirmado',
  closing: 'Encerrando sessão',
  closed: 'Sessão encerrada',
  expired: 'Sessão expirada',
  error: 'A execução precisa de atenção',
}

export function acceptSnapshot(current: Session | null, next: Session): Session {
  return current?.id === next.id && current.sequence > next.sequence ? current : next
}

export async function request<T>(path: string, options: RequestInit = {}): Promise<T> {
  const response = await fetch(`/api${path}`, { credentials: 'same-origin', ...options })
  const data = await response.json()
  if (!response.ok) {
    throw new Error(
      typeof data.detail === 'string' ? data.detail : 'Não foi possível concluir esta solicitação.',
    )
  }
  return data as T
}

export function json(text: object): RequestInit {
  return {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(text),
  }
}
