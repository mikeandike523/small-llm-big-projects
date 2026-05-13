import { placeholderCss } from "../../css/DebugPanel";
import { EnvInfo, SkillsInfo, ToolsInfo } from "../../types/DebugPanel";
import InfoRow from "./InfoRow";
import SkillsCard from "./SkillsCard";
import ToolsCard from "./ToolsCard";

export default function SystemTab({ pwd, sessionId, envInfo, skillsInfo, toolsInfo }: {
    pwd: string;
    sessionId: string;
    envInfo: EnvInfo | null;
    skillsInfo: SkillsInfo | null;
    toolsInfo: ToolsInfo | null
}) {
    return (
        <>
            {sessionId && <InfoRow label="Session ID" value={sessionId} />}
            {envInfo && (
                <>
                    <InfoRow label="OS" value={envInfo.os} />
                    <InfoRow label="Shell" value={envInfo.shell} />
                    <InfoRow label="Initial CWD" value={envInfo.initialCwd} />
                </>
            )}
            {pwd && <InfoRow label="Working Directory" value={pwd} />}
            {skillsInfo && <SkillsCard skillsInfo={skillsInfo} />}
            {toolsInfo && <ToolsCard toolsInfo={toolsInfo} />}
            {!sessionId && !envInfo && !pwd && !skillsInfo && !toolsInfo && (
                <div css={placeholderCss}>No system info available.</div>
            )}
        </>
    )
}