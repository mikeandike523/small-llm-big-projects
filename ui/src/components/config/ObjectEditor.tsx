/** @jsxImportSource @emotion/react */
import { css } from "@emotion/react";
import Editor from "@monaco-editor/react";

const editorWrapperCss = css`
  border: 1px solid #2a3a5a;
  border-radius: 4px;
  overflow: hidden;
`;

type Props = {
  value: string;
  onChange: (value: string) => void;
  height?: number;
};

export default function ObjectEditor({ value, onChange, height = 120 }: Props) {
  return (
    <div css={editorWrapperCss}>
      <Editor
        height={height}
        defaultLanguage="json"
        theme="vs-dark"
        value={value}
        onChange={(v) => onChange(v ?? "")}
        options={{
          minimap: { enabled: false },
          scrollBeyondLastLine: false,
          lineNumbers: "off",
          glyphMargin: false,
          folding: false,
          lineDecorationsWidth: 0,
          lineNumbersMinChars: 0,
          renderLineHighlight: "none",
          fontSize: 12,
          wordWrap: "on",
          scrollbar: {
            vertical: "auto",
            horizontal: "hidden",
          },
        }}
      />
    </div>
  );
}
