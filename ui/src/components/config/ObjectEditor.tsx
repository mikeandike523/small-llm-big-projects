/** @jsxImportSource @emotion/react */
import { css } from "@emotion/react";
import { useEffect, useRef, useState } from "react";
import { inputCss, noBtnCss, rotateBtnCss } from "../../css/config/TokensTab";

type KVPair = { key: string; value: string };

function parseToKV(jsonStr: string): KVPair[] {
  if (!jsonStr || !jsonStr.trim()) return [];
  try {
    const obj = JSON.parse(jsonStr);
    if (typeof obj !== "object" || Array.isArray(obj) || obj === null) return [];
    return Object.entries(obj).map(([k, v]) => ({ key: k, value: JSON.stringify(v) }));
  } catch {
    return [];
  }
}

function serializeFromKV(pairs: KVPair[]): string {
  const obj: Record<string, unknown> = {};
  for (const { key, value } of pairs) {
    if (!key || !value.trim()) continue;
    try {
      obj[key] = JSON.parse(value);
    } catch {
      continue;
    }
  }
  return JSON.stringify(obj);
}

function jsonEqual(a: string, b: string): boolean {
  try {
    return (
      JSON.stringify(JSON.parse(a || "{}")) ===
      JSON.stringify(JSON.parse(b || "{}"))
    );
  } catch {
    return a === b;
  }
}

function isValidJson(s: string): boolean {
  if (!s.trim()) return true;
  try {
    JSON.parse(s);
    return true;
  } catch {
    return false;
  }
}

const innerTableCss = css`
  border-collapse: collapse;
  width: 100%;
  margin-bottom: 4px;
`;

const kvInputCss = css`
  ${inputCss}
  width: 100%;
  box-sizing: border-box;
  min-width: 0;
`;

const invalidInputCss = css`
  ${kvInputCss}
  border-color: #cc4444;
  &:focus {
    border-color: #ee5555;
  }
`;

const smallBtnCss = css`
  ${rotateBtnCss}
  font-size: 11px;
  padding: 2px 8px;
`;

const delBtnCss = css`
  ${noBtnCss}
  padding: 1px 6px;
  font-size: 11px;
  line-height: 1.4;
  color: #884444;
  border-color: transparent;
  &:hover {
    color: #cc4444;
    border-color: #3a1a1a;
    background: #2a0a0a;
  }
`;

const hintTextCss = css`
  font-size: 10px;
  color: #6f7f9e;
  margin-left: 8px;
`;

type Props = {
  value: string;
  onChange: (value: string) => void;
};

export default function ObjectEditor({ value, onChange }: Props) {
  const [pairs, setPairs] = useState<KVPair[]>(() => parseToKV(value));
  const lastEmittedRef = useRef<string>(serializeFromKV(parseToKV(value)));

  useEffect(() => {
    if (!jsonEqual(value, lastEmittedRef.current)) {
      const newPairs = parseToKV(value);
      setPairs(newPairs);
      lastEmittedRef.current = serializeFromKV(newPairs);
    }
  }, [value]);

  function emit(newPairs: KVPair[]) {
    const serialized = serializeFromKV(newPairs);
    lastEmittedRef.current = serialized;
    onChange(serialized);
  }

  function update(newPairs: KVPair[]) {
    setPairs(newPairs);
    emit(newPairs);
  }

  return (
    <div>
      {pairs.length > 0 && (
        <table css={innerTableCss}>
          <colgroup>
            <col style={{ width: "38%" }} />
            <col style={{ width: "56%" }} />
            <col style={{ width: "6%" }} />
          </colgroup>
          <tbody>
            {pairs.map((pair, idx) => {
              const valBad = pair.value.trim() !== "" && !isValidJson(pair.value);
              return (
                <tr key={idx}>
                  <td style={{ padding: "2px 4px 2px 0" }}>
                    <input
                      css={kvInputCss}
                      placeholder="key"
                      value={pair.key}
                      onChange={(e) =>
                        update(
                          pairs.map((p, i) =>
                            i === idx ? { ...p, key: e.target.value } : p,
                          ),
                        )
                      }
                    />
                  </td>
                  <td style={{ padding: "2px 4px" }}>
                    <input
                      css={valBad ? invalidInputCss : kvInputCss}
                      placeholder='"text" or 42 or true'
                      title={valBad ? "Invalid JSON — strings need quotes" : undefined}
                      value={pair.value}
                      onChange={(e) =>
                        update(
                          pairs.map((p, i) =>
                            i === idx ? { ...p, value: e.target.value } : p,
                          ),
                        )
                      }
                    />
                  </td>
                  <td style={{ padding: "2px 0", textAlign: "center" }}>
                    <button
                      css={delBtnCss}
                      title="Remove field"
                      onClick={() => update(pairs.filter((_, i) => i !== idx))}
                    >
                      ✕
                    </button>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      )}
      <div style={{ display: "flex", alignItems: "center" }}>
        <button css={smallBtnCss} onClick={() => update([...pairs, { key: "", value: "" }])}>
          + Add Field
        </button>
        {pairs.length === 0 && <span css={hintTextCss}>empty object</span>}
      </div>
    </div>
  );
}
