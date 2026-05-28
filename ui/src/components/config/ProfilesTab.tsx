/** @jsxImportSource @emotion/react */
import { css } from "@emotion/react";
import { useEffect, useMemo, useState } from "react";
import {
  actionsCss,
  addBtnCss,
  containerCss,
  deleteBtnCss,
  errorBannerCss,
  iconBtnCss,
  inputCss,
  noBtnCss,
  rotateBtnCss,
  tableCss,
  tableWrapCss,
  tdCss,
  thCss,
  topBarCss,
} from "../../css/config/TokensTab";

type TokenOption = {
  id: number;
  provider: string;
  name: string;
  label: string;
};

type ParamSpec = {
  name: string;
  value_type: "boolean" | "float" | "integer" | "object" | "string";
  min?: number;
  max?: number;
  description?: string;
};

type ActiveToken = { provider: string; name: string } | null;

type ProfileRow = {
  name: string;
  is_default: boolean;
  model: string;
  active_token: ActiveToken;
  params: Record<string, unknown>;
};

type ConfigPayload = {
  default_profile: string | null;
  profiles: ProfileRow[];
  tokens: TokenOption[];
  param_specs: ParamSpec[];
};

const panelTitleCss = css`
  font-size: 12px;
  color: #f2f6ff;
  text-transform: uppercase;
  letter-spacing: 1px;
`;

const selectCss = css`
  ${inputCss}
  cursor: pointer;
`;

const splitCss = css`
  display: grid;
  grid-template-columns: minmax(360px, 0.85fr) minmax(420px, 1.15fr);
  gap: 18px;
  align-items: start;

  @media (max-width: 980px) {
    grid-template-columns: 1fr;
  }
`;

const hintCss = css`
  color: #6f7f9e;
  font-size: 11px;
  line-height: 1.4;
`;

function tokenValue(token: ActiveToken, tokens: TokenOption[]) {
  if (!token) return "";
  const match = tokens.find(
    (t) => t.provider === token.provider && t.name === token.name,
  );
  return match ? String(match.id) : "";
}

function formatParamValue(value: unknown) {
  if (value === undefined || value === null) return "";
  if (typeof value === "object") return JSON.stringify(value, null, 2);
  return String(value);
}

function profileLabel(profile: ProfileRow) {
  return profile.is_default ? `${profile.name} (default)` : profile.name;
}

export default function ProfilesTab() {
  const [data, setData] = useState<ConfigPayload | null>(null);
  const [selectedProfile, setSelectedProfile] = useState<string | null>(null);
  const [newName, setNewName] = useState("");
  const [modelDrafts, setModelDrafts] = useState<Record<string, string>>({});
  const [paramDrafts, setParamDrafts] = useState<Record<string, string>>({});
  const [error, setError] = useState<string | null>(null);

  async function refresh(keepSelection = true) {
    const res = await fetch("/api/profiles/config");
    const payload = await res.json();
    setData(payload);
    if (
      !keepSelection ||
      !payload.profiles.some((p: ProfileRow) => p.name === selectedProfile)
    ) {
      setSelectedProfile(
        payload.default_profile ||
          (payload.profiles.length > 0 ? payload.profiles[0].name : null),
      );
    }
  }

  useEffect(() => {
    refresh(false);
  }, []);

  const selected = useMemo(() => {
    if (!selectedProfile) return null;
    return data?.profiles.find((p) => p.name === selectedProfile) ?? null;
  }, [data, selectedProfile]);

  function currentModel(profile: ProfileRow) {
    return modelDrafts[profile.name] ?? profile.model;
  }

  function paramKey(profile: string, param: string) {
    return `${profile}\u0000${param}`;
  }

  function currentParamValue(profile: ProfileRow, spec: ParamSpec) {
    const key = paramKey(profile.name, spec.name);
    return paramDrafts[key] ?? formatParamValue(profile.params[spec.name]);
  }

  async function checkedFetch(url: string, init: RequestInit) {
    setError(null);
    const res = await fetch(url, init);
    if (!res.ok) {
      const payload = await res.json();
      setError(payload.error || "Request failed");
      return false;
    }
    await refresh();
    return true;
  }

  async function createProfile() {
    const name = newName.trim();
    if (!name) return;
    const ok = await checkedFetch("/api/profiles", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ name }),
    });
    if (ok) {
      setNewName("");
      setSelectedProfile(name);
    }
  }

  async function setDefaultProfile(name: string) {
    await checkedFetch("/api/profiles/default", {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ name }),
    });
  }

  async function saveModel(profile: ProfileRow) {
    const model = currentModel(profile).trim();
    const ok = await checkedFetch(`/api/profiles/${profile.name}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ model }),
    });
    if (ok) {
      setModelDrafts((drafts) => {
        const next = { ...drafts };
        delete next[profile.name];
        return next;
      });
    }
  }

  async function saveToken(profile: ProfileRow, tokenId: string) {
    await checkedFetch(`/api/profiles/${profile.name}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ token_id: tokenId }),
    });
  }

  async function saveParam(profile: ProfileRow, spec: ParamSpec) {
    const key = paramKey(profile.name, spec.name);
    const value = currentParamValue(profile, spec);
    const ok = await checkedFetch(
      `/api/profiles/${profile.name}/params/${spec.name}`,
      {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ value }),
      },
    );
    if (ok) {
      setParamDrafts((drafts) => {
        const next = { ...drafts };
        delete next[key];
        return next;
      });
    }
  }

  async function unsetParam(profile: ProfileRow, spec: ParamSpec) {
    await checkedFetch(`/api/profiles/${profile.name}/params/${spec.name}`, {
      method: "DELETE",
    });
  }

  async function deleteProfile(profile: ProfileRow) {
    await checkedFetch(`/api/profiles/${profile.name}`, { method: "DELETE" });
  }

  if (!data) {
    return <div css={hintCss}>Loading profiles...</div>;
  }

  return (
    <div css={containerCss}>
      <div css={topBarCss}>
        <span style={{ fontSize: 12, color: "#8a9ab8" }}>
          Default profile:{" "}
          <span style={{ color: data.default_profile ? "#3ccc6c" : "#cc6666" }}>
            {data.default_profile ?? "(none)"}
          </span>
        </span>
        <div css={actionsCss}>
          <input
            css={inputCss}
            style={{ width: 180 }}
            placeholder="profile name"
            value={newName}
            onChange={(e) => setNewName(e.target.value)}
          />
          <button css={addBtnCss} onClick={createProfile}>
            Add Profile
          </button>
        </div>
      </div>

      {error && <div css={errorBannerCss}>{error}</div>}

      <div css={splitCss}>
        <div css={containerCss}>
          <div css={panelTitleCss}>Profiles</div>
          <div css={tableWrapCss}>
            <table css={tableCss}>
              <thead>
                <tr>
                  <th css={thCss}>Name</th>
                  <th css={thCss}>Active Token</th>
                  <th css={thCss}>Actions</th>
                </tr>
              </thead>
              <tbody>
                {data.profiles.map((profile) => (
                  <tr key={profile.name}>
                    <td css={tdCss}>
                      <button
                        css={iconBtnCss}
                        style={{
                          color:
                            profile.name === selectedProfile
                              ? "#f2f6ff"
                              : "#8a9ab8",
                          fontWeight: profile.is_default ? 700 : 400,
                        }}
                        onClick={() => setSelectedProfile(profile.name)}
                      >
                        {profileLabel(profile)}
                      </button>
                    </td>
                    <td css={tdCss}>
                      <select
                        css={selectCss}
                        value={tokenValue(profile.active_token, data.tokens)}
                        onChange={(e) => saveToken(profile, e.target.value)}
                      >
                        <option value="">No active token</option>
                        {data.tokens.map((token) => (
                          <option key={token.id} value={token.id}>
                            {token.label}
                          </option>
                        ))}
                      </select>
                    </td>
                    <td css={tdCss}>
                      <div css={actionsCss}>
                        <button
                          css={rotateBtnCss}
                          disabled={profile.is_default}
                          onClick={() => setDefaultProfile(profile.name)}
                        >
                          Set Default
                        </button>
                        <button
                          css={deleteBtnCss}
                          title="Delete profile"
                          onClick={() => deleteProfile(profile)}
                        >
                          Delete
                        </button>
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>

        <div css={containerCss}>
          <div css={panelTitleCss}>
            {selected?.name ?? "Profile"} Parameters
          </div>
          {selected && (
            <>
              <div css={tableWrapCss}>
                <table css={tableCss}>
                  <tbody>
                    <tr>
                      <th css={thCss}>Model</th>
                      <td css={tdCss}>
                        <input
                          css={inputCss}
                          value={currentModel(selected)}
                          onChange={(e) =>
                            setModelDrafts((drafts) => ({
                              ...drafts,
                              [selected.name]: e.target.value,
                            }))
                          }
                        />
                      </td>
                      <td css={tdCss}>
                        <button
                          css={rotateBtnCss}
                          onClick={() => saveModel(selected)}
                        >
                          Save
                        </button>
                      </td>
                    </tr>
                  </tbody>
                </table>
              </div>

              <div css={tableWrapCss}>
                <table css={tableCss}>
                  <thead>
                    <tr>
                      <th css={thCss}>Param</th>
                      <th css={thCss}>Value</th>
                      <th css={thCss}>Type</th>
                      <th css={thCss}>Actions</th>
                    </tr>
                  </thead>
                  <tbody>
                    {data.param_specs.map((spec) => {
                      const key = paramKey(selected.name, spec.name);
                      const value = currentParamValue(selected, spec);
                      return (
                        <tr key={spec.name} title={spec.description}>
                          <td css={tdCss}>{spec.name}</td>
                          <td css={tdCss}>
                            {spec.value_type === "boolean" ? (
                              <select
                                css={selectCss}
                                value={value}
                                onChange={(e) =>
                                  setParamDrafts((drafts) => ({
                                    ...drafts,
                                    [key]: e.target.value,
                                  }))
                                }
                              >
                                <option value="">Unset</option>
                                <option value="true">true</option>
                                <option value="false">false</option>
                              </select>
                            ) : (
                              <input
                                css={inputCss}
                                type={
                                  spec.value_type === "integer" ||
                                  spec.value_type === "float"
                                    ? "number"
                                    : "text"
                                }
                                min={spec.min}
                                max={spec.max}
                                step={spec.value_type === "integer" ? 1 : "any"}
                                value={value}
                                placeholder="unset"
                                onChange={(e) =>
                                  setParamDrafts((drafts) => ({
                                    ...drafts,
                                    [key]: e.target.value,
                                  }))
                                }
                              />
                            )}
                          </td>
                          <td css={tdCss}>
                            <span css={hintCss}>
                              {spec.value_type}
                              {spec.min !== undefined ? ` >= ${spec.min}` : ""}
                              {spec.max !== undefined ? ` <= ${spec.max}` : ""}
                            </span>
                          </td>
                          <td css={tdCss}>
                            <div css={actionsCss}>
                              <button
                                css={rotateBtnCss}
                                onClick={() => saveParam(selected, spec)}
                              >
                                Save
                              </button>
                              <button
                                css={noBtnCss}
                                onClick={() => unsetParam(selected, spec)}
                              >
                                Unset
                              </button>
                            </div>
                          </td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
            </>
          )}
        </div>
      </div>
    </div>
  );
}
