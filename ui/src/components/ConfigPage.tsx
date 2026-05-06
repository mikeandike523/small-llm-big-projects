/** @jsxImportSource @emotion/react */
import { css } from '@emotion/react'
import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import TokensTab from './config/TokensTab'

const TABS = ['Tokens'] as const
type Tab = typeof TABS[number]

const pageCss = css`
  display: flex;
  flex-direction: column;
  height: 100%;
  background: #0f0f0f;
  color: #e0e0e0;
  font-family: 'Fira Code', 'Consolas', monospace;
`

const headerCss = css`
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 18px 28px 0;
  border-bottom: 1px solid #1e1e1e;
  flex-shrink: 0;
`

const leftHeaderCss = css`
  display: flex;
  flex-direction: column;
  gap: 2px;
`

const h1Css = css`
  font-size: 18px;
  font-weight: 700;
  color: #f2f6ff;
  letter-spacing: 2px;
  text-transform: uppercase;
`

const backBtnCss = css`
  background: none;
  border: 1px solid #30405f;
  border-radius: 5px;
  color: #8a9ab8;
  font-size: 12px;
  font-family: inherit;
  padding: 6px 14px;
  cursor: pointer;
  &:hover { border-color: #8aa4d8; color: #eef3ff; }
`

const tabBarCss = css`
  display: flex;
  gap: 0;
  align-self: flex-end;
`

const tabCss = css`
  background: none;
  border: none;
  border-bottom: 2px solid transparent;
  color: #8a9ab8;
  font-family: inherit;
  font-size: 13px;
  padding: 10px 20px;
  cursor: pointer;
  transition: color 0.12s;
  &:hover { color: #e0e0e0; }
`

const activeTabCss = css`
  color: #f2f6ff;
  border-bottom-color: #4a6aee;
`

const contentCss = css`
  flex: 1;
  overflow-y: auto;
  padding: 24px 28px;

  &::-webkit-scrollbar { width: 6px; }
  &::-webkit-scrollbar-track { background: #0a0a0a; }
  &::-webkit-scrollbar-thumb { background: #2f4f86; border-radius: 3px; }
  &::-webkit-scrollbar-thumb:hover { background: #4f73b3; }
`

export default function ConfigPage() {
  const [tab, setTab] = useState<Tab>('Tokens')
  const navigate = useNavigate()

  return (
    <div css={pageCss}>
      <div css={headerCss}>
        <div css={leftHeaderCss}>
          <h1 css={h1Css}>Configuration</h1>
        </div>
        <div style={{ display: 'flex', alignItems: 'center', gap: 16, alignSelf: 'center' }}>
          <nav css={tabBarCss}>
            {TABS.map(t => (
              <button key={t} css={[tabCss, t === tab && activeTabCss]} onClick={() => setTab(t)}>
                {t}
              </button>
            ))}
          </nav>
          <button css={backBtnCss} onClick={() => navigate('/')}>← Dashboard</button>
        </div>
      </div>
      <main css={contentCss}>
        {tab === 'Tokens' && <TokensTab />}
      </main>
    </div>
  )
}
