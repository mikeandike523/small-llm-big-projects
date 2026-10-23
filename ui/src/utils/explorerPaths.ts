/** True when `path` is `ancestor` itself or lies anywhere beneath it. */
export function isPathWithin(path: string, ancestor: string): boolean {
  return path === ancestor || path.startsWith(`${ancestor}/`);
}

/** Where `path` ends up after `oldPath` is renamed to `newPath`, else null. */
export function retargetPath(
  path: string,
  oldPath: string,
  newPath: string,
): string | null {
  return isPathWithin(path, oldPath)
    ? `${newPath}${path.slice(oldPath.length)}`
    : null;
}
