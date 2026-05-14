/** @jsxImportSource @emotion/react */
import { css } from "@emotion/react";
import { useEffect, useState } from "react";
import { RotateDialog } from "./RotateDialog";
import { AddTokenDialog } from "./AddTokenDialog";
import { containerCss, topBarCss, addBtnCss, errorBannerCss, tableWrapCss, tableCss, thCss, tdCss, activeTrCss, inputCss, activeLabelCss, rotateBtnCss, actionsCss, iconBtnCss, confirmDeleteCss, yesDeleteBtnCss, noBtnCss, deleteBtnCss } from "../../css/config/TokensTab";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

type TokenRow = {
  id: number;
  provider: string;
  name: string;
  endpoint_url: string;
  masked_value: string;
};

type ActiveToken = { provider: string; name: string; profile: string };
type Draft = { provider: string; name: string; endpoint_url: string };



// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export default function TokensTab() {
  const [tokens, setTokens] = useState<TokenRow[]>([]);
  const [active, setActive] = useState<ActiveToken | null>(null);
  const [editingId, setEditingId] = useState<number | null>(null);
  const [draft, setDraft] = useState<Draft | null>(null);
  const [rotateId, setRotateId] = useState<number | null>(null);
  const [addOpen, setAddOpen] = useState(false);
  const [deleteConfirmId, setDeleteConfirmId] = useState<number | null>(null);
  const [copyStatus, setCopyStatus] = useState<
    Record<number, "idle" | "ok" | "err">
  >({});
  const [saveError, setSaveError] = useState<string | null>(null);

  async function refresh() {
    const [tRes, aRes] = await Promise.all([
      fetch("/api/tokens"),
      fetch("/api/tokens/active"),
    ]);
    setTokens((await tRes.json()).tokens);
    setActive(await aRes.json());
  }

  useEffect(() => {
    refresh();
  }, []);

  function isActive(row: TokenRow) {
    return (
      active !== null &&
      active.provider === row.provider &&
      active.name === row.name
    );
  }

  function startEdit(row: TokenRow) {
    setSaveError(null);
    setEditingId(row.id);
    setDraft({
      provider: row.provider,
      name: row.name,
      endpoint_url: row.endpoint_url,
    });
  }

  async function saveEdit(row: TokenRow) {
    if (!draft) return;
    const trimmed = {
      provider: draft.provider.trim(),
      name: draft.name.trim(),
      endpoint_url: draft.endpoint_url.trim(),
    };
    const payload: Record<string, string> = {};
    if (trimmed.provider !== row.provider) payload.provider = trimmed.provider;
    if (trimmed.name !== row.name) payload.name = trimmed.name;
    if (trimmed.endpoint_url !== row.endpoint_url)
      payload.endpoint_url = trimmed.endpoint_url;
    if (Object.keys(payload).length === 0) {
      cancelEdit();
      return;
    }

    const res = await fetch(`/api/tokens/${row.id}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    if (!res.ok) {
      setSaveError((await res.json()).error);
      return;
    }
    cancelEdit();
    refresh();
  }

  function cancelEdit() {
    setEditingId(null);
    setDraft(null);
    setSaveError(null);
  }

  async function copyValue(id: number) {
    const res = await fetch(`/api/tokens/${id}/value`);
    if (!res.ok) {
      setCopyStatus((s) => ({ ...s, [id]: "err" }));
      return;
    }
    await navigator.clipboard.writeText((await res.json()).value);
    setCopyStatus((s) => ({ ...s, [id]: "ok" }));
    setTimeout(() => setCopyStatus((s) => ({ ...s, [id]: "idle" })), 2000);
  }

  async function downloadToken(id: number) {
    const res = await fetch(`/api/tokens/${id}/value`);
    if (!res.ok) return;
    const data = await res.json();
    const blob = new Blob([JSON.stringify(data, null, 2)], {
      type: "application/json",
    });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `${data.provider}${data.name ? "-" + data.name : ""}.json`;
    a.click();
    URL.revokeObjectURL(url);
  }

  async function deleteToken(id: number) {
    await fetch(`/api/tokens/${id}`, { method: "DELETE" });
    setDeleteConfirmId(null);
    refresh();
  }

  const rotateRow =
    rotateId !== null ? tokens.find((t) => t.id === rotateId) : null;
  const rotateLabel = rotateRow
    ? `${rotateRow.provider}${rotateRow.name ? " / " + rotateRow.name : ""}`
    : "";

  return (
    <div css={containerCss}>
      <div css={topBarCss}>
        <span style={{ fontSize: 12, color: "#8a9ab8" }}>
          {tokens.length} token{tokens.length !== 1 ? "s" : ""}
          {active && (
            <span style={{ marginLeft: 10, color: "#3ccc6c" }}>
              Active: {active.provider}
              {active.name ? " / " + active.name : ""} (profile:{" "}
              {active.profile})
            </span>
          )}
        </span>
        <button css={addBtnCss} onClick={() => setAddOpen(true)}>
          + Add Token
        </button>
      </div>

      {saveError && <div css={errorBannerCss}>{saveError}</div>}

      <div css={tableWrapCss}>
        <table css={tableCss}>
          <thead>
            <tr>
              <th css={thCss}>Provider</th>
              <th css={thCss}>Name</th>
              <th css={thCss}>Endpoint URL</th>
              <th css={thCss}>Value</th>
              <th css={thCss}>Actions</th>
            </tr>
          </thead>
          <tbody>
            {tokens.length === 0 && (
              <tr>
                <td
                  css={tdCss}
                  colSpan={5}
                  style={{ color: "#555", textAlign: "center", padding: 24 }}
                >
                  No tokens stored. Click "+ Add Token" to add one.
                </td>
              </tr>
            )}
            {tokens.map((row) => {
              const editing = editingId === row.id;
              const active_ = isActive(row);
              const copyState = copyStatus[row.id] ?? "idle";

              return (
                <tr
                  key={row.id}
                  css={active_ ? activeTrCss : undefined}
                  title={
                    active_ && active
                      ? `Active token — profile: ${active.profile}`
                      : undefined
                  }
                >
                  <td css={tdCss}>
                    {editing ? (
                      <input
                        css={inputCss}
                        value={draft!.provider}
                        onChange={(e) =>
                          setDraft(
                            (d) => d && { ...d, provider: e.target.value },
                          )
                        }
                      />
                    ) : (
                      <span>
                        {row.provider}
                        {active_ && <span css={activeLabelCss}>active</span>}
                      </span>
                    )}
                  </td>
                  <td css={tdCss}>
                    {editing ? (
                      <input
                        css={inputCss}
                        value={draft!.name}
                        onChange={(e) =>
                          setDraft((d) => d && { ...d, name: e.target.value })
                        }
                      />
                    ) : (
                      <span style={{ color: row.name ? "#e0e0e0" : "#555" }}>
                        {row.name || "(no name)"}
                      </span>
                    )}
                  </td>
                  <td css={tdCss}>
                    {editing ? (
                      <input
                        css={inputCss}
                        value={draft!.endpoint_url}
                        onChange={(e) =>
                          setDraft(
                            (d) => d && { ...d, endpoint_url: e.target.value },
                          )
                        }
                      />
                    ) : (
                      <span
                        style={{ color: row.endpoint_url ? "#e0e0e0" : "#555" }}
                      >
                        {row.endpoint_url || "(none)"}
                      </span>
                    )}
                  </td>
                  <td css={tdCss}>
                    <div
                      style={{ display: "flex", alignItems: "center", gap: 8 }}
                    >
                      <span style={{ color: "#556", fontFamily: "monospace" }}>
                        {row.masked_value}
                      </span>
                      <button
                        css={rotateBtnCss}
                        onClick={() => setRotateId(row.id)}
                      >
                        Rotate
                      </button>
                    </div>
                  </td>
                  <td css={tdCss}>
                    {editing ? (
                      <div css={actionsCss}>
                        <button
                          css={iconBtnCss}
                          title="Save"
                          onClick={() => saveEdit(row)}
                        >
                          💾
                        </button>
                        <button
                          css={iconBtnCss}
                          title="Cancel"
                          onClick={cancelEdit}
                        >
                          ✕
                        </button>
                      </div>
                    ) : deleteConfirmId === row.id ? (
                      <div css={confirmDeleteCss}>
                        <span style={{ fontSize: 11, color: "#cc6666" }}>
                          Delete?
                        </span>
                        <button
                          css={yesDeleteBtnCss}
                          onClick={() => deleteToken(row.id)}
                        >
                          Yes
                        </button>
                        <button
                          css={noBtnCss}
                          onClick={() => setDeleteConfirmId(null)}
                        >
                          No
                        </button>
                      </div>
                    ) : (
                      <div css={actionsCss}>
                        <button
                          css={iconBtnCss}
                          title="Edit"
                          onClick={() => startEdit(row)}
                        >
                          ✏️
                        </button>
                        <button
                          css={iconBtnCss}
                          title={
                            copyState === "ok"
                              ? "Copied!"
                              : copyState === "err"
                                ? "Error"
                                : "Copy value"
                          }
                          onClick={() => copyValue(row.id)}
                          style={{
                            color:
                              copyState === "ok"
                                ? "#3ccc6c"
                                : copyState === "err"
                                  ? "#cc6666"
                                  : undefined,
                          }}
                        >
                          {copyState === "ok" ? "✓" : "📋"}
                        </button>
                        <button
                          css={iconBtnCss}
                          title="Download as JSON"
                          onClick={() => downloadToken(row.id)}
                        >
                          ⬇
                        </button>
                        <button
                          css={deleteBtnCss}
                          title="Delete"
                          onClick={() => setDeleteConfirmId(row.id)}
                        >
                          🗑
                        </button>
                      </div>
                    )}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>

      {rotateId !== null && (
        <RotateDialog
          tokenId={rotateId}
          tokenLabel={rotateLabel}
          onClose={() => setRotateId(null)}
          onSuccess={() => {
            setRotateId(null);
            refresh();
          }}
        />
      )}

      {addOpen && (
        <AddTokenDialog
          onClose={() => setAddOpen(false)}
          onSuccess={() => {
            setAddOpen(false);
            refresh();
          }}
        />
      )}
    </div>
  );
}
