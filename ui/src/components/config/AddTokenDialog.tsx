/** @jsxImportSource @emotion/react */
import { css } from '@emotion/react'
import { useState } from 'react'
import * as Dialog from '@radix-ui/react-dialog'

interface Props {
  onClose: () => void
  onSuccess: () => void
}

const overlayCss = css`
  position: fixed;
  inset: 0;
  background: rgba(0, 0, 0, 0.7);
  z-index: 1000;
`

const contentCss = css`
  position: fixed;
  top: 50%;
  left: 50%;
  transform: translate(-50%, -50%);
  background: #1a1a1a;
  border: 1px solid #333;
  border-radius: 8px;
  padding: 24px;
  min-width: 420px;
  max-width: 560px;
  width: 90%;
  z-index: 1001;
  font-family: 'Fira Code', 'Consolas', monospace;
  display: flex;
  flex-direction: column;
  gap: 14px;
  position: relative;
`

const titleCss = css`
  font-size: 15px;
  font-weight: 700;
  color: #f2f6ff;
  letter-spacing: 1px;
`

const fieldGroupCss = css`
  display: flex;
  flex-direction: column;
  gap: 4px;
`

const labelCss = css`
  font-size: 11px;
  color: #8a9ab8;
  text-transform: uppercase;
  letter-spacing: 1px;
`

const inputCss = css`
  width: 100%;
  background: #111;
  border: 1px solid #333;
  border-radius: 5px;
  color: #e0e0e0;
  font-family: 'Fira Code', 'Consolas', monospace;
  font-size: 12px;
  padding: 8px 10px;
  outline: none;
  &:focus { border-color: #4a6aee; }
`

const textareaCss = css`
  ${inputCss};
  resize: vertical;
`

const requiredMarkCss = css`
  color: #cc6666;
  margin-left: 3px;
`

const errorCss = css`
  font-size: 12px;
  color: #cc6666;
`

const footerCss = css`
  display: flex;
  justify-content: flex-end;
  gap: 10px;
`

const cancelBtnCss = css`
  background: none;
  border: 1px solid #30405f;
  border-radius: 5px;
  color: #eef3ff;
  padding: 7px 18px;
  font-size: 12px;
  font-family: inherit;
  cursor: pointer;
  &:hover { border-color: #8aa4d8; }
`

const addBtnCss = css`
  background: #1a1a2e;
  border: 1px solid #2a3a6e;
  border-radius: 5px;
  color: #7b9cff;
  padding: 7px 18px;
  font-size: 12px;
  font-family: inherit;
  cursor: pointer;
  font-weight: 600;
  &:hover:not(:disabled) { background: #222244; border-color: #4a6aee; }
  &:disabled { opacity: 0.5; cursor: not-allowed; }
`

const closeBtnCss = css`
  position: absolute;
  top: 14px;
  right: 14px;
  background: none;
  border: none;
  color: #8a9ab8;
  font-size: 14px;
  cursor: pointer;
  line-height: 1;
  &:hover { color: #e0e0e0; }
`

export function AddTokenDialog({ onClose, onSuccess }: Props) {
  const [form, setForm] = useState({ provider: '', name: '', endpoint: '', value: '' })
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(false)

  function set(field: keyof typeof form) {
    return (e: React.ChangeEvent<HTMLInputElement | HTMLTextAreaElement>) =>
      setForm(f => ({ ...f, [field]: e.target.value }))
  }

  async function handleSubmit() {
    const trimmed = {
      provider: form.provider.trim(),
      name:     form.name.trim(),
      endpoint: form.endpoint.trim() || undefined,
      value:    form.value.trim(),
    }
    if (!trimmed.provider) { setError('Provider is required'); return }
    if (!trimmed.value)    { setError('Value is required'); return }
    setLoading(true)
    setError(null)
    const res = await fetch('/api/tokens', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(trimmed),
    })
    setLoading(false)
    if (!res.ok) { setError((await res.json()).error); return }
    onSuccess()
  }

  return (
    <Dialog.Root open onOpenChange={open => !open && onClose()}>
      <Dialog.Portal>
        <Dialog.Overlay css={overlayCss} />
        <Dialog.Content css={contentCss}>
          <Dialog.Title css={titleCss}>Add Token</Dialog.Title>

          <div css={fieldGroupCss}>
            <label css={labelCss}>Provider<span css={requiredMarkCss}>*</span></label>
            <input css={inputCss} value={form.provider} onChange={set('provider')}
              placeholder="e.g. openai, anthropic" autoFocus />
          </div>

          <div css={fieldGroupCss}>
            <label css={labelCss}>Name <span style={{ color: '#555' }}>(optional)</span></label>
            <input css={inputCss} value={form.name} onChange={set('name')}
              placeholder="e.g. production, personal" />
          </div>

          <div css={fieldGroupCss}>
            <label css={labelCss}>Endpoint URL <span style={{ color: '#555' }}>(optional)</span></label>
            <input css={inputCss} value={form.endpoint} onChange={set('endpoint')}
              placeholder="e.g. https://api.openai.com/v1" />
          </div>

          <div css={fieldGroupCss}>
            <label css={labelCss}>Token Value<span css={requiredMarkCss}>*</span></label>
            <textarea css={textareaCss} value={form.value} onChange={set('value')}
              placeholder="Paste token value..." rows={3} />
          </div>

          {error && <p css={errorCss}>{error}</p>}

          <div css={footerCss}>
            <Dialog.Close asChild>
              <button css={cancelBtnCss}>Cancel</button>
            </Dialog.Close>
            <button css={addBtnCss} onClick={handleSubmit} disabled={loading}>
              {loading ? 'Adding...' : 'Add'}
            </button>
          </div>

          <Dialog.Close asChild>
            <button css={closeBtnCss} aria-label="Close">✕</button>
          </Dialog.Close>
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  )
}
