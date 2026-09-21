/** @jsxImportSource @emotion/react */
import { css } from "@emotion/react";
import { useEffect, useRef } from "react";
import { useNavigate } from "react-router-dom";
import { TerminalPanel } from "./TerminalPanel";
import { createSocket } from "../socket";
import {
  fontMono,
  spBorder,
  spHeaderBg,
  spTextMain,
} from "../css/SidePanelTheme";
import { dashboardButtonCss } from "../css/Chat";

const pageBarCss = css`
  display: flex;
  align-items: center;
  height: 40px;
  padding: 0 12px;
  background: ${spHeaderBg};
  border-bottom: 1px solid ${spBorder};
  flex-shrink: 0;
  gap: 12px;
`;

const pageTitleCss = css`
  font-family: ${fontMono};
  font-size: 12px;
  text-transform: uppercase;
  letter-spacing: 0.08em;
  color: ${spTextMain};
`;

const fillCss = css`
  flex: 1;
`;

const pageContainerCss = css`
  display: flex;
  flex-direction: column;
  height: 100%;
  min-width: 0;
  background: #0f0f0f;
`;

export default function TerminalPage() {
  const navigate = useNavigate();
  const socketRef = useRef(createSocket());
  const socket = socketRef.current;

  useEffect(() => {
    socket.connect();
    return () => {
      socket.disconnect();
    };
  }, [socket]);

  return (
    <div css={pageContainerCss}>
      <div css={pageBarCss}>
        <button
          css={dashboardButtonCss}
          onClick={() => navigate("/")}
          title="Return to dashboard"
          aria-label="Return to dashboard"
        >
          ⌂
        </button>
        <span css={pageTitleCss}>Terminal</span>
        <div css={fillCss} />
      </div>
      <TerminalPanel variant="page" socket={socket} />
    </div>
  );
}
