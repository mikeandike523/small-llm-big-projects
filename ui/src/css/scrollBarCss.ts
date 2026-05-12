import { css } from '@emotion/react'

const scrollbarCss = css`
  &::-webkit-scrollbar { width: 6px; }
  &::-webkit-scrollbar-track { background: #0a0a0a; }
  &::-webkit-scrollbar-thumb { background: #2f4f86; border-radius: 3px; }
  &::-webkit-scrollbar-thumb:hover { background: #4f73b3; }
`

export default scrollbarCss