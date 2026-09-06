import { Socket } from "socket.io-client";

export interface SkillsInfo {
  enabled: boolean;
  count: number;
  path: string | null;
  files: string[];
}

export interface EnvInfo {
  os: string;
  shell: string;
  initialCwd: string;
}

export interface ToolsInfo {
  totalCount: number;
  builtinCount: number;
  builtinPath: string;
  names: string[];
  customPlugins: { name: string; count: number; path: string }[] | null;
}

export type BackendLogContent =
  string | number | boolean | null | Record<string, unknown> | unknown[];

export interface BackendLogSingleEntry {
  id: number;
  multiple?: false;
  content: BackendLogContent;
}

export interface BackendLogMultiEntry {
  id: number;
  multiple: true;
  content: BackendLogContent[];
}

export type BackendLogEntry = BackendLogSingleEntry | BackendLogMultiEntry;

export interface MemKeyEvent {
  key: string;
  type: "modified" | "deleted";
}

export interface Props {
  open: boolean;
  onToggle: () => void;
  pwd: string;
  sessionId: string;
  envInfo: EnvInfo | null;
  skillsInfo: SkillsInfo | null;
  toolsInfo: ToolsInfo | null;
  systemPrompt: string | null;
  backendLogs: BackendLogEntry[];
  socket: Socket;
}
