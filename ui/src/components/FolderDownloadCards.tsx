/** @jsxImportSource @emotion/react */
import { FiArchive, FiCheck, FiXCircle } from "react-icons/fi";
import type { FolderDownloadCard } from "../hooks/useSessionDownloads";
import {
  downloadCardCss,
  downloadCardsCss,
  downloadCardTitleCss,
  downloadDetailCss,
  downloadProgressFillCss,
  downloadProgressTrackCss,
  downloadStatusIconCss,
} from "../css/FolderDownloadCards";

function formatBytes(value: number): string {
  if (value < 1024) return `${value} B`;
  const units = ["KB", "MB", "GB", "TB"];
  let size = value;
  let unit = -1;
  do {
    size /= 1024;
    unit += 1;
  } while (size >= 1024 && unit < units.length - 1);
  return `${size.toFixed(size >= 10 ? 1 : 2)} ${units[unit]}`;
}

function cardDetail(card: FolderDownloadCard): string {
  if (card.state === "starting") return "Starting preparation…";
  if (card.state === "discovering") {
    const suffix = card.fileCount === 1 ? "file" : "files";
    return `Discovering files… ${card.fileCount} ${suffix} found`;
  }
  if (card.state === "zipping") {
    const bytes = `${formatBytes(card.processedBytes)} / ${formatBytes(card.totalInputBytes)}`;
    return `Zipping ${card.filesProcessed} of ${card.fileCount} files · ${bytes}`;
  }
  if (card.state === "ready") return "Archive ready. Download started.";
  if (card.state === "complete") return "Download started.";
  return card.error || "Could not prepare the archive.";
}

export default function FolderDownloadCards({
  cards,
}: {
  cards: FolderDownloadCard[];
}) {
  if (cards.length === 0) return null;
  return (
    <div
      css={downloadCardsCss}
      aria-live="polite"
      aria-label="Folder downloads"
    >
      {cards.map((card) => {
        const progress =
          card.state === "zipping" && card.totalInputBytes > 0
            ? Math.min(100, (card.processedBytes / card.totalInputBytes) * 100)
            : null;
        return (
          <div key={card.id} css={downloadCardCss(card.state === "failed")}>
            <span css={downloadStatusIconCss(card.state === "failed")}>
              {card.state === "failed" ? (
                <FiXCircle size={18} />
              ) : card.state === "ready" || card.state === "complete" ? (
                <FiCheck size={18} />
              ) : (
                <FiArchive size={18} />
              )}
            </span>
            <div>
              <div css={downloadCardTitleCss}>{card.downloadName}</div>
              <div css={downloadDetailCss}>{cardDetail(card)}</div>
              {card.state !== "failed" && card.state !== "ready" && (
                <div css={downloadProgressTrackCss}>
                  <div css={downloadProgressFillCss(progress)} />
                </div>
              )}
              {card.state === "failed" && (
                <div css={downloadDetailCss}>Check Debug Panel logs.</div>
              )}
            </div>
          </div>
        );
      })}
    </div>
  );
}
