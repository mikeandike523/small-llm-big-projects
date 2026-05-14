/** @jsxImportSource @emotion/react */
import { Global, css } from "@emotion/react";
import { Routes, Route } from "react-router-dom";
import Chat from "./components/Chat";
import Dashboard from "./components/Dashboard";
import ConfigPage from "./components/ConfigPage";

const globalCss = css`
  *,
  *::before,
  *::after {
    box-sizing: border-box;
    margin: 0;
    padding: 0;
  }

  html,
  body,
  #root {
    height: 100%;
  }

  body {
    background: #0f0f0f;
  }
`;

export default function App() {
  return (
    <>
      <Global styles={globalCss} />
      <Routes>
        <Route path="/" element={<Dashboard />} />
        <Route path="/session" element={<Chat />} />
        <Route path="/config" element={<ConfigPage />} />
      </Routes>
    </>
  );
}
