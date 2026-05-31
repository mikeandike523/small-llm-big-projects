/** @jsxImportSource @emotion/react */
import { css } from "@emotion/react";
import { useEffect, useState, useCallback } from "react";

const GATEWAY_URL =
  (window as any).__GATEWAY_URL__ ?? window.location.origin;

// ── types ──────────────────────────────────────────────────────────────────

type NsKey = "model" | "watchdog.model" | "summarizer.model" | "patchrewriter.model";

interface ParamsData {
  model: Record<string, unknown>;
  "watchdog.model": Record<string, unknown>;
  "summarizer.model": Record<string, unknown>;
  "patchrewriter.model": Record<string, unknown>;
  system: Record<string, unknown>;
}

const NS_LABELS: Record<NsKey | "system", string> = {
  model: "Model — main agentic loop",
  "watchdog.model": "Watchdog — YES/NO samplers, task titles, skill selection, process triage",
  "summarizer.model": "Summarizer — subturn compaction, summarize_memory_item tool",
  "patchrewriter.model": "Patch Rewriter — unified diff repair",
  system: "System",
};

const SAMPLER_FIELDS: { suffix: string }[] = [
  { suffix: "temperature" },
  { suffix: "top_p" },
  { suffix: "top_k" },
  { suffix: "max_tokens" },
  { suffix: "request_extra_params" },
];

// System params: full param name, which data bucket to read from, and the key within that bucket.
const SYSTEM_PARAMS: { name: string; ns: string; suffix: string; bucketKey: string; bucket: keyof ParamsData }[] = [
  { name: "model.irat",                      ns: "model",  suffix: "irat",                      bucketKey: "irat",                            bucket: "model"  },
  { name: "system.return_value_max_chars",   ns: "system", suffix: "return_value_max_chars",   bucketKey: "system.return_value_max_chars",   bucket: "system" },
  { name: "system.blank_response_retries",   ns: "system", suffix: "blank_response_retries",   bucketKey: "system.blank_response_retries",   bucket: "system" },
];

// ── styles ─────────────────────────────────────────────────────────────────

const tabCss = css`
  padding: 24px 28px;
  display: flex;
  flex-direction: column;
  gap: 24px;
  overflow-y: auto;
  height: 100%;
  box-sizing: border-box;
`;

const sectionCss = css`
  border: 1px solid #222;
  border-radius: 8px;
  overflow: hidden;
`;

const sectionHeaderCss = css`
  background: #161616;
  padding: 10px 16px;
  font-size: 12px;
  color: #7aa2e0;
  font-weight: 600;
  letter-spacing: 0.04em;
  text-transform: uppercase;
  cursor: pointer;
  user-select: none;
  display: flex;
  justify-content: space-between;
  align-items: center;
  &:hover { background: #1c1c1c; }
`;

const sectionBodyCss = css`
  padding: 16px;
  display: flex;
  flex-direction: column;
  gap: 12px;
  background: #0f0f0f;
`;

const rowCss = css`
  display: flex;
  align-items: center;
  gap: 12px;
`;

const labelCss = css`
  width: 220px;
  flex-shrink: 0;
  font-size: 13px;
  color: #9090a0;
  font-family: "Fira Code", monospace;
`;

const inputCss = css`
  flex: 1;
  background: #1a1a1a;
  border: 1px solid #2a2a2a;
  border-radius: 4px;
  color: #e0e0e0;
  font-family: "Fira Code", monospace;
  font-size: 13px;
  padding: 5px 8px;
  &:focus { outline: none; border-color: #4a6a9a; }
`;

const setButtonCss = css`
  background: #1a3a6a;
  border: none;
  border-radius: 4px;
  color: #9ec4f0;
  font-size: 12px;
  padding: 5px 12px;
  cursor: pointer;
  &:hover { background: #1e4a80; }
`;

const unsetButtonCss = css`
  background: #2a1a1a;
  border: none;
  border-radius: 4px;
  color: #c06060;
  font-size: 12px;
  padding: 5px 10px;
  cursor: pointer;
  &:hover { background: #3a2020; }
`;

const currentValueCss = css`
  font-size: 12px;
  color: #5a9a5a;
  font-family: "Fira Code", monospace;
  margin-left: 4px;
`;

const errorCss = css`
  color: #c06060;
  font-size: 12px;
`;

// ── helpers ────────────────────────────────────────────────────────────────

function formatValue(v: unknown): string {
  if (v === undefined || v === null) return "";
  if (typeof v === "object") return JSON.stringify(v);
  return String(v);
}

// ── component ──────────────────────────────────────────────────────────────

export default function ParamsTab() {
  const [data, setData] = useState<ParamsData | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [collapsed, setCollapsed] = useState<Record<string, boolean>>({});
  const [drafts, setDrafts] = useState<Record<string, string>>({});
  const [rowErrors, setRowErrors] = useState<Record<string, string>>({});

  const load = useCallback(async () => {
    try {
      const r = await fetch(`${GATEWAY_URL}/api/params`);
      if (!r.ok) throw new Error(await r.text());
      setData(await r.json());
      setLoadError(null);
    } catch (e: any) {
      setLoadError(e.message ?? "Failed to load params");
    }
  }, []);

  useEffect(() => { load(); }, [load]);

  const draftKey = (ns: string, suffix: string) => `${ns}.${suffix}`;

  function getDraft(ns: string, suffix: string, currentVal: unknown): string {
    const k = draftKey(ns, suffix);
    return k in drafts ? drafts[k] : formatValue(currentVal);
  }

  function setDraft(ns: string, suffix: string, val: string) {
    setDrafts(prev => ({ ...prev, [draftKey(ns, suffix)]: val }));
  }

  async function handleSet(ns: string, suffix: string) {
    const k = draftKey(ns, suffix);
    const raw = drafts[k] ?? "";
    const name = `${ns}.${suffix}`;
    try {
      const r = await fetch(`${GATEWAY_URL}/api/params/set`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ name, value: raw }),
      });
      const json = await r.json();
      if (!r.ok || json.error) throw new Error(json.error ?? "Failed");
      setRowErrors(prev => { const n = { ...prev }; delete n[k]; return n; });
      setDrafts(prev => { const n = { ...prev }; delete n[k]; return n; });
      await load();
    } catch (e: any) {
      setRowErrors(prev => ({ ...prev, [k]: e.message ?? "Error" }));
    }
  }

  async function handleUnset(ns: string, suffix: string) {
    const name = `${ns}.${suffix}`;
    const k = draftKey(ns, suffix);
    await fetch(`${GATEWAY_URL}/api/params/unset`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ name }),
    });
    setDrafts(prev => { const n = { ...prev }; delete n[k]; return n; });
    setRowErrors(prev => { const n = { ...prev }; delete n[k]; return n; });
    await load();
  }

  function toggleCollapse(ns: string) {
    setCollapsed(prev => ({ ...prev, [ns]: !prev[ns] }));
  }

  function ParamRow({ ns, suffix, currentVal, label }: { ns: string; suffix: string; currentVal: unknown; label?: string }) {
    const k = draftKey(ns, suffix);
    const isSet = currentVal !== undefined;
    const draft = getDraft(ns, suffix, currentVal);
    const err = rowErrors[k];
    return (
      <div>
        <div css={rowCss}>
          <span css={labelCss}>{label ?? suffix}</span>
          <input
            css={inputCss}
            value={draft}
            placeholder={suffix === "request_extra_params" ? '{"key":"value"}' : ""}
            onChange={e => setDraft(ns, suffix, e.target.value)}
            onKeyDown={e => { if (e.key === "Enter") handleSet(ns, suffix); }}
          />
          <button css={setButtonCss} onClick={() => handleSet(ns, suffix)}>Set</button>
          {isSet && (
            <button css={unsetButtonCss} onClick={() => handleUnset(ns, suffix)}>Unset</button>
          )}
          {isSet && !(draftKey(ns, suffix) in drafts) && (
            <span css={currentValueCss}>✓ {formatValue(currentVal)}</span>
          )}
        </div>
        {err && <div css={errorCss} style={{ marginLeft: 228, marginTop: 4 }}>{err}</div>}
      </div>
    );
  }

  if (loadError) return <div css={tabCss}><div css={errorCss}>{loadError}</div></div>;
  if (!data) return <div css={tabCss}><div style={{ color: "#666" }}>Loading...</div></div>;

  const sections: { ns: NsKey }[] = [
    { ns: "model" },
    { ns: "watchdog.model" },
    { ns: "summarizer.model" },
    { ns: "patchrewriter.model" },
  ];

  return (
    <div css={tabCss}>
      {sections.map(({ ns }) => {
        const nsData = data[ns] ?? {};
        const isOpen = !collapsed[ns];
        return (
          <div css={sectionCss} key={ns}>
            <div css={sectionHeaderCss} onClick={() => toggleCollapse(ns)}>
              <span>{NS_LABELS[ns]}</span>
              <span style={{ color: "#555", fontSize: 11 }}>{isOpen ? "▲" : "▼"}</span>
            </div>
            {isOpen && (
              <div css={sectionBodyCss}>
                {SAMPLER_FIELDS.map(({ suffix }) => (
                  <ParamRow key={suffix} ns={ns} suffix={suffix} currentVal={nsData[suffix]} />
                ))}
              </div>
            )}
          </div>
        );
      })}

      {/* System params: model.irat and system.return_value_max_chars */}
      <div css={sectionCss}>
        <div css={sectionHeaderCss} onClick={() => toggleCollapse("system")}>
          <span>{NS_LABELS.system}</span>
          <span style={{ color: "#555", fontSize: 11 }}>{!collapsed["system"] ? "▲" : "▼"}</span>
        </div>
        {!collapsed["system"] && (
          <div css={sectionBodyCss}>
            {SYSTEM_PARAMS.map(({ name, ns, suffix, bucketKey, bucket }) => (
              <ParamRow
                key={name}
                ns={ns}
                suffix={suffix}
                currentVal={data[bucket][bucketKey]}
                label={name}
              />
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
