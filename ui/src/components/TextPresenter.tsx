/** @jsxImportSource @emotion/react */
import { css } from "@emotion/react";
import { useState } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import rehypeHighlight from "rehype-highlight";
import { useStickToBottom } from "use-stick-to-bottom";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface TextPresenterProps {
  content: string;
  maxHeight: number;
  streaming?: boolean;
  initialMode?: "plain" | "markdown";
  /** Show the plain/MD toggle button. Default true. */
  showToggle?: boolean;
}

// ---------------------------------------------------------------------------
// Styles
// ---------------------------------------------------------------------------

const toggleBarCss = css`
  display: flex;
  justify-content: flex-end;
  margin-bottom: 2px;
`;

const toggleBtnCss = css`
  background: transparent;
  border: 1px solid #30405f;
  color: #e8efff;
  border-radius: 4px;
  padding: 1px 7px;
  font-size: 11px;
  cursor: pointer;
  font-family: inherit;
  &:hover {
    color: #fff;
    border-color: #8aa4d8;
  }
`;

const scrollbarCss = css`
  &::-webkit-scrollbar {
    width: 6px;
  }
  &::-webkit-scrollbar-track {
    background: #0a0a0a;
  }
  &::-webkit-scrollbar-thumb {
    background: #2f4f86;
    border-radius: 3px;
  }
  &::-webkit-scrollbar-thumb:hover {
    background: #4f73b3;
  }
`;

const scrollContainerCss = (maxHeight: number) => css`
  ${scrollbarCss}
  max-height: ${maxHeight}px;
  overflow-y: auto;
`;

const plainCss = css`
  white-space: pre-wrap;
  word-break: break-word;
`;

const markdownCss = css`
  word-break: break-word;

  p {
    margin: 0.4em 0;
  }
  p:first-child {
    margin-top: 0;
  }
  p:last-child {
    margin-bottom: 0;
  }

  h1,
  h2,
  h3,
  h4,
  h5,
  h6 {
    margin: 0.6em 0 0.3em;
    font-weight: 600;
    line-height: 1.3;
  }
  h1 {
    font-size: 1.4em;
  }
  h2 {
    font-size: 1.25em;
  }
  h3 {
    font-size: 1.1em;
  }

  ul,
  ol {
    padding-left: 1.5em;
    margin: 0.4em 0;
  }
  li {
    margin: 0.2em 0;
  }

  blockquote {
    border-left: 3px solid #4f73b3;
    padding-left: 0.8em;
    color: #edf2ff;
    margin: 0.4em 0;
    font-style: italic;
  }

  code {
    background: #192335;
    padding: 0.15em 0.35em;
    border-radius: 4px;
    font-family: "Consolas", "Monaco", monospace;
    font-size: 0.9em;
  }

  pre {
    background: #0f1726;
    border: 1px solid #30405f;
    border-radius: 6px;
    padding: 10px 12px;
    overflow-x: auto;
    margin: 0.5em 0;
  }

  pre code {
    background: none;
    padding: 0;
    border-radius: 0;
    font-size: 0.85em;
    line-height: 1.5;
  }

  a {
    color: #7aa2e0;
    text-decoration: none;
  }
  a:hover {
    text-decoration: underline;
  }

  hr {
    border: none;
    border-top: 1px solid #30405f;
    margin: 0.6em 0;
  }

  table {
    border-collapse: collapse;
    width: 100%;
    margin: 0.5em 0;
    font-size: 0.9em;
  }
  th {
    background: #182233;
    padding: 6px 10px;
    text-align: left;
    border: 1px solid #30405f;
  }
  td {
    padding: 5px 10px;
    border: 1px solid #30405f;
  }
  tr:nth-child(even) td {
    background: #101722;
  }

  .hljs {
    background: transparent !important;
  }
`;

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export function TextPresenter({
  content,
  maxHeight,
  initialMode = "markdown",
  showToggle = true,
}: TextPresenterProps) {
  const [mode, setMode] = useState<"plain" | "markdown">(initialMode);
  const { scrollRef, contentRef } = useStickToBottom();

  return (
    <div>
      {showToggle && (
        <div css={toggleBarCss}>
          <button
            css={toggleBtnCss}
            onClick={() =>
              setMode((m) => (m === "plain" ? "markdown" : "plain"))
            }
          >
            {mode === "plain" ? "MD" : "Raw"}
          </button>
        </div>
      )}
      <div ref={scrollRef} css={scrollContainerCss(maxHeight)}>
        <div ref={contentRef}>
          {mode === "plain" ? (
            <div css={plainCss}>{content}</div>
          ) : (
            <div css={markdownCss}>
              <ReactMarkdown
                remarkPlugins={[remarkGfm]}
                rehypePlugins={[rehypeHighlight]}
              >
                {content}
              </ReactMarkdown>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
