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
  | string
  | number
  | boolean
  | null
  | Record<string, unknown>
  | unknown[];

// `seq` is assigned client-side on arrival (hooks/backendLogBuffer.ts) and
// strictly increases across server and client entries. `id` cannot be used
// for ordering: client-originated entries use negative ids.
export interface BackendLogSingleEntry {
  id: number;
  seq: number;
  multiple?: false;
  content: BackendLogContent;
}

export interface BackendLogMultiEntry {
  id: number;
  seq: number;
  multiple: true;
  content: BackendLogContent[];
}

export type BackendLogEntry = BackendLogSingleEntry | BackendLogMultiEntry;

// The `backend_log` socket payload, before a `seq` is assigned.
export type BackendLogWireEntry =
  | Omit<BackendLogSingleEntry, "seq">
  | Omit<BackendLogMultiEntry, "seq">;

export interface MemKeyEvent {
  key: string;
  type: "modified" | "deleted";
}

export interface Props {
  open: boolean;
  pwd: string;
  sessionId: string;
  envInfo: EnvInfo | null;
  skillsInfo: SkillsInfo | null;
  toolsInfo: ToolsInfo | null;
  systemPrompt: string | null;
  backendLogs: BackendLogEntry[];
  socket: Socket;
}
