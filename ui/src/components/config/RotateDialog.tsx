/** @jsxImportSource @emotion/react */
import { css } from '@emotion/react'
import { useState } from 'react'
import * as Dialog from '@radix-ui/react-dialog'

interface Props {
  tokenId: number
  tokenLabel: string
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
`

const titleCss = css`
  font-size: 15px;
  font-weight: 700;
  color: #f2f6ff;
  letter-spacing: 1px;
`

const descCss = css`
  font-size: 12px;
  color: #8a9ab8;
`

const textareaCss = css`
  width: 100%;
  background: #111;
  border: 1px solid #333;
  border-radius: 5px;
  color: #e0e0e0;
  font-family: 'Fira Code', 'Consolas', monospace;
  font-size: 12px;
  padding: 10px;
  resize: vertical;
  outline: none;
  &:focus { border-color: #4a6aee; }
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

const okBtnCss = css`
  background: #1a1a2e;
  border: 1px solid #2a3a6e;
  border-radius: 5px;
  color: #7b9cff;
  padding: 7px 18px;
  font-size: 12px;
  font-family: inherit;
  cursor: pointer;
  font-weight: 600;
  &:hover { background: #222244; border-color: #4a6aee; }
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

export function RotateDialog({ tokenId, tokenLabel, onClose, onSuccess }: Props) {
  const [value, setValue] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(false)

  async function handleOk() {
    const trimmed = value.trim()
    if (!trimmed) { setError('Value cannot be empty'); return }
    setLoading(true)
    setError(null)
    const res = await fetch(`/api/tokens/${tokenId}/rotate`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ value: trimmed }),
    })
    setLoading(false)
    if (!res.ok) { setError((await res.json()).error); return }
    onSuccess()
  }

  return (
    <Dialog.Root open onOpenChange={open => !open && onClose()}>
      <Dialog.Portal>
        <Dialog.Overlay css={overlayCss} />
        <Dialog.Content css={[contentCss, css`position:relative;`]}>
          <Dialog.Title css={titleCss}>Rotate Token Value</Dialog.Title>
          <Dialog.Description css={descCss}>{tokenLabel}</Dialog.Description>
          <textarea
            css={textareaCss}
            value={value}
            onChange={e => setValue(e.target.value)}
            placeholder="Paste new token value..."
            rows={4}
            autoFocus
          />
          {error && <p css={errorCss}>{error}</p>}
          <div css={footerCss}>
            <Dialog.Close asChild>
              <button css={cancelBtnCss}>Cancel</button>
            </Dialog.Close>
            <button css={okBtnCss} onClick={handleOk} disabled={loading}>
              {loading ? 'Saving...' : 'OK'}
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
