/** @jsxImportSource @emotion/react */
import { FiChevronLeft, FiChevronRight } from "react-icons/fi";
import {
  dividerBadgeCss,
  dividerCss,
  dividerIconWrapCss,
  dividerLabelCss,
} from "../css/SidePanelTheme";

interface Props {
  open: boolean;
  onToggle: () => void;
  label: string;
  // Which screen edge this divider is pinned to. The chevron points inward
  // (toward center) to invite opening, and outward (toward the edge) to
  // invite collapsing.
  side: "left" | "right";
  badge?: number;
}

export default function PanelDivider({
  open,
  onToggle,
  label,
  side,
  badge,
}: Props) {
  const inward = side === "left" ? "right" : "left";
  const outward = side === "left" ? "left" : "right";
  const pointsRight = (open ? outward : inward) === "right";
  const Icon = pointsRight ? FiChevronRight : FiChevronLeft;

  return (
    <div
      css={dividerCss}
      onClick={onToggle}
      role="button"
      tabIndex={0}
      aria-label={`${open ? "Collapse" : "Expand"} ${label} panel`}
      title={`${open ? "Collapse" : "Expand"} ${label} panel`}
      onKeyDown={(e) => {
        if (e.key === "Enter" || e.key === " ") {
          e.preventDefault();
          onToggle();
        }
      }}
    >
      <span css={dividerIconWrapCss}>
        <Icon size={15} />
      </span>
      <span css={dividerLabelCss}>{label}</span>
      {!!badge && <span css={dividerBadgeCss}>{badge}</span>}
    </div>
  );
}
