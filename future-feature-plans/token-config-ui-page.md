# Implementation Plan: `/config/tokens` UI Page

## Overview

Add a `/config` route with a tabbed interface (first tab: Tokens). The Tokens tab is a SQL-viewer-style table for managing tokens stored in the `tokens` MySQL table, with row-level editing, value rotation via dialog, copy-to-clipboard, and download-as-JSON — all without ever sending the full token value in list responses.

---

## File Structure

```
src/
  config_routes/
    __init__.py          (new — empty package)
    tokens.py            (new — all token HTTP routes)
ui/src/
  components/
    ConfigPage.tsx       (new — tabbed /config container)
    config/
      TokensTab.tsx      (new — table + row editing logic)
      RotateDialog.tsx   (new — modal: paste new value)
      AddTokenDialog.tsx (new — modal: add new token form)
  App.tsx                (edit — add /config route)
src/ui_connector/
  app.py                 (edit — import config_routes so routes register)
```

---

## Part 1 — Backend

### 1.1 `src/config_routes/__init__.py` — new, empty

Marks the directory as a Python package. No code needed; the module-level side effects (route registration) happen in `tokens.py`.

### 1.2 `src/config_routes/tokens.py` — new

Imports `app` from `src.ui_connector.app` using the same decorator pattern that `socket_handlers.py` uses. The import itself is the registration — no `register_routes(app)` call needed.

**Helpers:**

```python
def _mask(value: str) -> str:
    if not value or len(value) <= 4:
        return "****"
    return f"{value[:2]}****{value[-2:]}"

def _maybe_add_known_provider(cursor, provider: str, endpoint: str) -> None:
    """Insert into known_providers if provider not already there. Never overwrites."""
    cursor.execute(
        "SELECT 1 FROM known_providers WHERE BINARY provider_key = BINARY %s LIMIT 1",
        (provider,),
    )
    if cursor.fetchone() is None:
        cursor.execute(
            "INSERT INTO known_providers (provider_key, display_name, default_endpoint_url)"
            " VALUES (%s, %s, %s)",
            (provider, provider, endpoint),
        )
```

**Endpoints:**

| Route | Method | Purpose | Notes |
|---|---|---|---|
| `/api/tokens` | GET | List all tokens (masked) | Returns `{tokens: [{id,provider,name,endpoint_url,masked_value}]}` |
| `/api/tokens/active` | GET | Active token for current profile | Returns `{provider,name,profile}` or `null` |
| `/api/tokens` | POST | Add new token | 409 if `(provider,name)` already exists |
| `/api/tokens/<int:id>` | PATCH | Edit provider/name/endpoint | Whitespace-stripped; known_providers side-effect on endpoint change; 409 on uniqueness violation |
| `/api/tokens/<int:id>/rotate` | POST | Update value only | Body: `{value}`. No endpoint side-effect (mirrors CLI rotate-without-endpoint) |
| `/api/tokens/<int:id>/value` | GET | Full token value | Returns `{provider,name,endpoint,value}` for copy/download |
| `/api/tokens/<int:id>` | DELETE | Delete token | 404 if not found |

**POST /api/tokens — add only (no silent rotate; 409 on duplicate):**

```python
@app.route("/api/tokens", methods=["POST"])
def api_tokens_add():
    data = request.get_json(force=True, silent=True) or {}
    provider = (data.get("provider") or "").strip()
    name     = (data.get("name")     or "").strip()
    endpoint = (data.get("endpoint") or "").strip() or None
    value    = (data.get("value")    or "").strip()
    if not provider: return jsonify({"error": "provider is required"}), 400
    if not value:    return jsonify({"error": "value is required"}), 400
    pool = get_pool()
    with pool.get_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                "SELECT 1 FROM tokens WHERE BINARY provider=BINARY %s"
                " AND BINARY token_name=BINARY %s LIMIT 1", (provider, name))
            if cursor.fetchone():
                return jsonify({"error": f'Token ({provider!r}, {name!r}) already exists.'
                                         ' Use the Rotate button to update its value.'}), 409
            cursor.execute(
                "INSERT INTO tokens (provider, endpoint_url, token_name, token_value)"
                " VALUES (%s,%s,%s,%s)", (provider, endpoint, name, value))
            if endpoint:
                _maybe_add_known_provider(cursor, provider, endpoint)
        conn.commit()
    return jsonify({"ok": True})
```

**PATCH /api/tokens/<id> — field edits with endpoint side-effect:**

```python
@app.route("/api/tokens/<int:token_id>", methods=["PATCH"])
def api_tokens_patch(token_id: int):
    data = request.get_json(force=True, silent=True) or {}
    pool = get_pool()
    with pool.get_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                "SELECT provider, token_name, endpoint_url FROM tokens WHERE id=%s", (token_id,))
            row = cursor.fetchone()
        if not row:
            return jsonify({"error": "Token not found"}), 404
        old_provider, old_name, old_endpoint = row

        new_provider = (data.get("provider") or old_provider).strip()
        new_name     = (data["name"] if "name" in data else old_name or "").strip()
        endpoint_in_payload = "endpoint_url" in data
        new_endpoint = ((data.get("endpoint_url") or "").strip() or None) \
                        if endpoint_in_payload else old_endpoint

        if (new_provider, new_name) != (old_provider, old_name):
            with conn.cursor() as cursor:
                cursor.execute(
                    "SELECT 1 FROM tokens WHERE BINARY provider=BINARY %s"
                    " AND BINARY token_name=BINARY %s AND id!=%s LIMIT 1",
                    (new_provider, new_name, token_id))
                if cursor.fetchone():
                    return jsonify({"error": "That provider+name combination is already taken"}), 409

        with conn.cursor() as cursor:
            cursor.execute(
                "UPDATE tokens SET provider=%s, token_name=%s, endpoint_url=%s WHERE id=%s",
                (new_provider, new_name, new_endpoint, token_id))
            if endpoint_in_payload and new_endpoint and new_endpoint != old_endpoint:
                _maybe_add_known_provider(cursor, new_provider, new_endpoint)
        conn.commit()
    return jsonify({"ok": True})
```

**POST /api/tokens/<id>/rotate — value only:**

```python
@app.route("/api/tokens/<int:token_id>/rotate", methods=["POST"])
def api_tokens_rotate(token_id: int):
    data  = request.get_json(force=True, silent=True) or {}
    value = (data.get("value") or "").strip()
    if not value:
        return jsonify({"error": "value is required"}), 400
    pool = get_pool()
    with pool.get_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute("UPDATE tokens SET token_value=%s WHERE id=%s", (value, token_id))
            if cursor.rowcount == 0:
                return jsonify({"error": "Token not found"}), 404
        conn.commit()
    return jsonify({"ok": True})
```

### 1.3 Edit `src/ui_connector/app.py` — register routes

Add at the very bottom, mirroring the existing socket_handlers import:

```python
import src.config_routes.tokens  # noqa: E402, F401
```

---

## Part 2 — Frontend

### 2.1 Install `@radix-ui/react-dialog`

```
cd ui && pnpm add @radix-ui/react-dialog
```

Radix Dialog is the most widely used React dialog primitive. It renders into a Portal appended to `<body>`, provides a `DialogOverlay` for the backdrop (pointer-events blocked), focus-traps inside the modal, and handles Escape-to-close. Uses ARIA roles (`role="dialog"`, `aria-modal="true"`).

### 2.2 Edit `ui/src/App.tsx` — add `/config` route

```tsx
import ConfigPage from './components/ConfigPage'
// inside <Routes>:
<Route path="/config" element={<ConfigPage />} />
```

Also add a "Config" nav link to the Dashboard header so the page is reachable.

### 2.3 New `ui/src/components/ConfigPage.tsx` — tabbed shell

Owns tab state. Renders tab bar and delegates to child tab components. Future tabs (Profiles, etc.) added here.

```tsx
const TABS = ['Tokens'] as const
type Tab = typeof TABS[number]

export default function ConfigPage() {
  const [tab, setTab] = useState<Tab>('Tokens')
  return (
    <div css={pageCss}>
      <header css={headerCss}>
        <h1>Configuration</h1>
        <nav css={tabBarCss}>
          {TABS.map(t => (
            <button key={t} css={[tabCss, t === tab && activeCss]} onClick={() => setTab(t)}>
              {t}
            </button>
          ))}
        </nav>
      </header>
      <main css={contentCss}>
        {tab === 'Tokens' && <TokensTab />}
      </main>
    </div>
  )
}
```

Dark theme CSS matching existing app style (bg `#0f0f0f`, text `#e0e0e0`, accent border `#333`).

### 2.4 New `ui/src/components/config/TokensTab.tsx` — the main table

**Types:**

```ts
type TokenRow = {
  id: number
  provider: string
  name: string
  endpoint_url: string
  masked_value: string
}
type ActiveToken = { provider: string; name: string; profile: string }
type Draft = { provider: string; name: string; endpoint_url: string }
```

**State:**

```ts
const [tokens, setTokens]               = useState<TokenRow[]>([])
const [active, setActive]               = useState<ActiveToken | null>(null)
const [editingId, setEditingId]         = useState<number | null>(null)
const [draft, setDraft]                 = useState<Draft | null>(null)
const [rotateId, setRotateId]           = useState<number | null>(null)
const [addOpen, setAddOpen]             = useState(false)
const [deleteConfirmId, setDeleteConfirmId] = useState<number | null>(null)
const [copyStatus, setCopyStatus]       = useState<Record<number, 'idle'|'ok'|'err'>>({})
const [error, setError]                 = useState<string | null>(null)
```

**Data fetching:**

```ts
async function refresh() {
  const [tRes, aRes] = await Promise.all([
    fetch('/api/tokens'), fetch('/api/tokens/active')
  ])
  setTokens((await tRes.json()).tokens)
  setActive(await aRes.json())  // null if no active token
}
useEffect(() => { refresh() }, [])
```

**Active row detection:**

```ts
function isActive(row: TokenRow) {
  return active !== null
    && active.provider === row.provider
    && active.name === row.name
}
```

**Edit flow:**

```ts
function startEdit(row: TokenRow) {
  setEditingId(row.id)
  setDraft({ provider: row.provider, name: row.name, endpoint_url: row.endpoint_url })
}

async function saveEdit(row: TokenRow) {
  const trimmed = {
    provider:     draft!.provider.trim(),
    name:         draft!.name.trim(),
    endpoint_url: draft!.endpoint_url.trim(),
  }
  const payload: Record<string, string> = {}
  if (trimmed.provider     !== row.provider)     payload.provider     = trimmed.provider
  if (trimmed.name         !== row.name)         payload.name         = trimmed.name
  if (trimmed.endpoint_url !== row.endpoint_url) payload.endpoint_url = trimmed.endpoint_url
  if (Object.keys(payload).length === 0) { cancelEdit(); return }

  const res = await fetch(`/api/tokens/${row.id}`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  })
  if (!res.ok) { setError((await res.json()).error); return }
  cancelEdit()
  refresh()
}

function cancelEdit() { setEditingId(null); setDraft(null) }
```

**Copy flow:**

```ts
async function copyValue(id: number) {
  const res = await fetch(`/api/tokens/${id}/value`)
  if (!res.ok) { setCopyStatus(s => ({ ...s, [id]: 'err' })); return }
  await navigator.clipboard.writeText((await res.json()).value)
  setCopyStatus(s => ({ ...s, [id]: 'ok' }))
  setTimeout(() => setCopyStatus(s => ({ ...s, [id]: 'idle' })), 2000)
}
```

**Download flow:**

```ts
async function downloadToken(id: number) {
  const res = await fetch(`/api/tokens/${id}/value`)
  if (!res.ok) return
  const data = await res.json()
  const blob = new Blob([JSON.stringify(data, null, 2)], { type: 'application/json' })
  const url  = URL.createObjectURL(blob)
  const a    = document.createElement('a')
  a.href     = url
  a.download = `${data.provider}${data.name ? '-' + data.name : ''}.json`
  a.click()
  URL.revokeObjectURL(url)
}
```

**Delete flow:**

```ts
async function deleteToken(id: number) {
  await fetch(`/api/tokens/${id}`, { method: 'DELETE' })
  setDeleteConfirmId(null)
  refresh()
}
```

**Table structure:**

Columns: Provider | Name | Endpoint URL | Value | Actions

- When `editingId === row.id`: Provider, Name, Endpoint URL cells render `<input>` bound to `draft`. Value cell is unchanged (still masked + Rotate button).
- Actions cell when editing: floppy-disc save icon + × cancel icon.
- Actions cell when not editing: pencil icon + Rotate button + copy icon + download icon + delete icon.
- Active row: `background: '#1a2a1a'` + `title` attribute on `<tr>`: `"Active token — profile: ${active.profile}"`.

**Delete confirmation:** inline — delete button changes to "Really delete?" + Yes / No buttons (no separate modal needed).

### 2.5 New `ui/src/components/config/RotateDialog.tsx`

Radix Dialog. Opened when `rotateId !== null`. Parent passes `tokenId`, `tokenLabel`, `onClose`, `onSuccess`.

```tsx
import * as Dialog from '@radix-ui/react-dialog'

export function RotateDialog({ tokenId, tokenLabel, onClose, onSuccess }: Props) {
  const [value, setValue] = useState('')
  const [error, setError] = useState<string | null>(null)

  async function handleOk() {
    const trimmed = value.trim()
    if (!trimmed) { setError('Value cannot be empty'); return }
    const res = await fetch(`/api/tokens/${tokenId}/rotate`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ value: trimmed }),
    })
    if (!res.ok) { setError((await res.json()).error); return }
    onSuccess()
  }

  return (
    <Dialog.Root open onOpenChange={open => !open && onClose()}>
      <Dialog.Portal>
        <Dialog.Overlay css={overlayCss} />
        <Dialog.Content css={contentCss}>
          <Dialog.Title>Rotate Token Value</Dialog.Title>
          <Dialog.Description css={descCss}>{tokenLabel}</Dialog.Description>
          <textarea css={textareaCss} value={value} onChange={e => setValue(e.target.value)}
            placeholder="Paste new token value..." rows={4} />
          {error && <p css={errorCss}>{error}</p>}
          <div css={footerCss}>
            <Dialog.Close asChild><button css={cancelBtnCss}>Cancel</button></Dialog.Close>
            <button css={okBtnCss} onClick={handleOk}>OK</button>
          </div>
          <Dialog.Close asChild>
            <button css={closeBtnCss} aria-label="Close">✕</button>
          </Dialog.Close>
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  )
}
```

Overlay: `position:fixed; inset:0; background:rgba(0,0,0,0.7)`.  
Content: `position:fixed; top:50%; left:50%; transform:translate(-50%,-50%); background:#1a1a1a; border:1px solid #333; border-radius:8px; padding:24px; min-width:400px`.

### 2.6 New `ui/src/components/config/AddTokenDialog.tsx`

Same Radix shell. Fields: Provider (required), Name (optional), Endpoint (optional), Value (required). Calls `POST /api/tokens`. Inline error for 409 conflicts and empty-field validation. On success: closes + `onSuccess()` → parent calls `refresh()`.

```tsx
export function AddTokenDialog({ onClose, onSuccess }: Props) {
  const [form, setForm] = useState({ provider: '', name: '', endpoint: '', value: '' })
  const [error, setError] = useState<string | null>(null)

  async function handleSubmit() {
    const trimmed = {
      provider: form.provider.trim(),
      name:     form.name.trim(),
      endpoint: form.endpoint.trim() || undefined,
      value:    form.value.trim(),
    }
    if (!trimmed.provider) { setError('Provider is required'); return }
    if (!trimmed.value)    { setError('Value is required'); return }
    const res = await fetch('/api/tokens', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(trimmed),
    })
    if (!res.ok) { setError((await res.json()).error); return }
    onSuccess()
  }

  return (
    <Dialog.Root open onOpenChange={open => !open && onClose()}>
      <Dialog.Portal>
        <Dialog.Overlay css={overlayCss} />
        <Dialog.Content css={contentCss}>
          <Dialog.Title>Add Token</Dialog.Title>
          {/* labeled inputs for: provider, name, endpoint, value */}
          {error && <p css={errorCss}>{error}</p>}
          <div css={footerCss}>
            <Dialog.Close asChild><button css={cancelBtnCss}>Cancel</button></Dialog.Close>
            <button css={okBtnCss} onClick={handleSubmit}>Add</button>
          </div>
          <Dialog.Close asChild>
            <button css={closeBtnCss} aria-label="Close">✕</button>
          </Dialog.Close>
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  )
}
```

---

## Execution Order

1. `src/config_routes/__init__.py` — create (empty)
2. `src/config_routes/tokens.py` — create (all 7 endpoints)
3. `src/ui_connector/app.py` — add one import line at bottom
4. `pnpm add @radix-ui/react-dialog` in `ui/`
5. `ui/src/App.tsx` — add `/config` route
6. `ui/src/components/ConfigPage.tsx` — create
7. `ui/src/components/config/RotateDialog.tsx` — create
8. `ui/src/components/config/AddTokenDialog.tsx` — create
9. `ui/src/components/config/TokensTab.tsx` — create (largest file)
10. Dashboard — add "Config" nav link
