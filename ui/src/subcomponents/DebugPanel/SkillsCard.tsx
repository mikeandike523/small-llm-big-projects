import {
  placeholderCss,
  skillsCardBodyCss,
  skillsCardCss,
  skillsCardFileCss,
  skillsCardHeaderCss,
  skillsCardPathCss,
} from "../../css/DebugPanel";
import { SkillsInfo } from "../../types/DebugPanel";
import InfoRow from "./InfoRow";

export default function SkillsCard({ skillsInfo }: { skillsInfo: SkillsInfo }) {
  if (!skillsInfo.enabled) {
    return <InfoRow label="Skills" value="Disabled" />;
  }
  return (
    <div css={skillsCardCss}>
      <div css={skillsCardHeaderCss}>
        {skillsInfo.count} skill{skillsInfo.count !== 1 ? "s" : ""} loaded
      </div>
      <div css={skillsCardBodyCss}>
        {skillsInfo.path && (
          <div css={skillsCardPathCss}>{skillsInfo.path}</div>
        )}
        {skillsInfo.files.length > 0 ? (
          skillsInfo.files.map((f) => (
            <div key={f} css={skillsCardFileCss}>
              · {f}
            </div>
          ))
        ) : (
          <div css={placeholderCss}>No skill files found.</div>
        )}
      </div>
    </div>
  );
}
