export function isJobActive(status: string | null | undefined): boolean {
  return status === "queued" || status === "running" || status === "retrying"
}

export function isJobTerminal(status: string | null | undefined): boolean {
  return status === "completed" || status === "failed" || status === "cancelled"
}
