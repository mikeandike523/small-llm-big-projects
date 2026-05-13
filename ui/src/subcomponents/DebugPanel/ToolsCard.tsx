import { skillsCardCss, skillsCardHeaderCss, skillsCardBodyCss, skillsCardPathCss, toolsCardPluginNameCss, toolsCardPluginPathCss, toolsCardDividerCss, toolsCardNameCss } from "../../css/DebugPanel";
import { ToolsInfo } from "../../types/DebugPanel";

export default function ToolsCard({ toolsInfo }: { toolsInfo: ToolsInfo }) {
  return (
    <div css={skillsCardCss}>
      <div css={skillsCardHeaderCss}>
        {toolsInfo.totalCount} tool{toolsInfo.totalCount !== 1 ? 's' : ''} loaded
      </div>
      <div css={skillsCardBodyCss}>
        <div css={skillsCardPathCss}>{toolsInfo.builtinPath} ({toolsInfo.builtinCount} built-in)</div>
        {toolsInfo.customPlugins && toolsInfo.customPlugins.length > 0 && (
          <>
            {toolsInfo.customPlugins.map(p => (
              <div key={p.name}>
                <div css={toolsCardPluginNameCss}>· {p.name}/ ({p.count} tools)</div>
                <div css={toolsCardPluginPathCss}>{p.path}</div>
              </div>
            ))}
          </>
        )}
        {toolsInfo.names.length > 0 && (
          <>
            <hr css={toolsCardDividerCss} />
            {toolsInfo.names.map(name => (
              <div key={name} css={toolsCardNameCss}>· {name}</div>
            ))}
          </>
        )}
      </div>
    </div>
  )
}