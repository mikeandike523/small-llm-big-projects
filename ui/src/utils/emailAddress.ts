// Live-typing feedback for email addresses. Mirrors the backend's
// src/utils/email_addresses.py rules; the backend stays the authority.
// ASCII only: anything else is rejected before any case change, and
// lowercasing touches A-Z only (never toLocaleLowerCase / Unicode mapping).

const DOMAIN_LABEL = /^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$/;
const PRINTABLE_ASCII_NO_SPACE = /^[\x21-\x7e]+$/;
const MAX_ADDRESS_LENGTH = 320;

export function asciiLower(value: string): string {
  return value.replace(/[A-Z]/g, (ch) =>
    String.fromCharCode(ch.charCodeAt(0) + 32),
  );
}

/** Why `raw` is not an acceptable address, or null when it is. */
export function emailAddressProblem(raw: string): string | null {
  const value = raw.trim();
  if (!value) return "is empty";
  if (value.length > MAX_ADDRESS_LENGTH)
    return `is longer than ${MAX_ADDRESS_LENGTH} characters`;
  // eslint-disable-next-line no-control-regex
  if (/[^\x00-\x7f]/.test(value))
    return "contains non-ASCII characters (use the xn-- form for international domains)";
  if (!PRINTABLE_ASCII_NO_SPACE.test(value))
    return "contains whitespace or control characters";
  const parts = value.split("@");
  if (parts.length !== 2) return "must contain exactly one '@'";
  const [local, domain] = parts;
  if (!local) return "is missing the part before '@'";
  if (/[<>()[\]\\,;:"]/.test(local))
    return "has characters not allowed before '@'";
  const labels = asciiLower(domain).split(".");
  if (labels.length < 2 || !labels.every((label) => DOMAIN_LABEL.test(label)))
    return "has an invalid domain";
  return null;
}

/** Problems with an allowed-senders textarea, one message per bad line. */
export function allowedSendersProblems(text: string): string[] {
  const problems: string[] = [];
  text.split(/\r\n|\r|\n/).forEach((line, index) => {
    if (!line.trim()) return;
    const problem = emailAddressProblem(line);
    if (problem) problems.push(`Line ${index + 1} (${line.trim()}) ${problem}`);
  });
  return problems;
}
