import { FitAddon } from "@xterm/addon-fit";
import { Terminal } from "@xterm/xterm";
import { Socket } from "socket.io-client";

export interface TerminalTabState {
  terminalId: string;
  name: string;
  cmdDisplay: string;
  xterm: Terminal | null;
  fitAddon: FitAddon | null;
  exited: boolean;
  exitCode: number | null;
}

export interface TerminalSessionState {
  terminal_id: string;
  name: string;
  cmd_display?: string;
  snapshot?: string;
}

export interface Props {
  open: boolean;
  onToggle: () => void;
  socket: Socket;
  busy: boolean;
}