/** @jsxImportSource @emotion/react */
import { Global, css } from '@emotion/react'
import Chat from './components/Chat'

const globalCss = css`
  *, *::before, *::after {
    box-sizing: border-box;
    margin: 0;
    padding: 0;
  }

  html, body, #root {
    height: 100%;
  }

  body {
    background: #0f0f0f;
  }
`

export default function App() {
  return (
    <>
      <Global styles={globalCss} />
      <Chat />
    </>
  )
}
