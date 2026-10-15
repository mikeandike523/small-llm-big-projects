import type { Monaco } from "@monaco-editor/react";

const disabledTypeScriptFeatures = {
  completionItems: false,
  hovers: false,
  documentSymbols: false,
  definitions: false,
  references: false,
  documentHighlights: false,
  rename: false,
  diagnostics: false,
  documentRangeFormattingEdits: false,
  signatureHelp: false,
  onTypeFormattingEdits: false,
  codeActions: false,
  inlayHints: false,
};

export function configureFileEditorLanguages(monaco: Monaco): void {
  // Keep Monaco's Monarch tokenizers, but do not register adapters that start
  // the TypeScript worker or try to construct a project from open models.
  monaco.languages.typescript.typescriptDefaults.setModeConfiguration(
    disabledTypeScriptFeatures,
  );
  monaco.languages.typescript.javascriptDefaults.setModeConfiguration(
    disabledTypeScriptFeatures,
  );
}

export function languageFor(path: string): string {
  const extension = path.split(".").pop()?.toLowerCase();
  const languages: Record<string, string> = {
    c: "c",
    cc: "cpp",
    cpp: "cpp",
    cs: "csharp",
    css: "css",
    go: "go",
    html: "html",
    java: "java",
    js: "javascript",
    json: "json",
    jsx: "javascript",
    md: "markdown",
    py: "python",
    rs: "rust",
    sh: "shell",
    sql: "sql",
    ts: "typescript",
    tsx: "typescript",
    xml: "xml",
    yaml: "yaml",
    yml: "yaml",
  };
  return languages[extension ?? ""] ?? "plaintext";
}
