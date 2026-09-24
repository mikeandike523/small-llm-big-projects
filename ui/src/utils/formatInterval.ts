// Reusable formatting for heartbeat interval values
export function formatIntervalMinutes(minutes: number): string {
  if (minutes >= 60 && minutes % 60 === 0) {
    return `${minutes / 60} hr`;
  }
  return `${minutes} min`;
}