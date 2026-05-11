// Extracted from Chat.tsx as "FormattedCostWithColor"

export default function FormattedCostWithColor(usd: number) {
    const costStr = usd.toFixed(4);
    const parts = costStr.split('.');
    if (parts.length !== 2) {
        throw new Error(`Unexpected cost format: ${costStr}`); // should never happen with the current formatCost implementation
    }
    const dollars = parts[0].padStart(2, '0');
    const cents = parts[1].slice(0, 2);
    const partialCents = parts[1].slice(2);
    return <>
    <span style={{ color: "#FFF" }}>{dollars}</span>
    <span style={{ color: "#FFF" }}>.</span>
    <span style={{ color: "#FFF" }}>{cents}</span>
    <span style={{ color: "#888" }}>{partialCents}</span>
  </>;
}
