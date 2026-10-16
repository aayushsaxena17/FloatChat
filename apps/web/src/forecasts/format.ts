export const STATUS_LABELS: Record<string, string> = {
  pending: "Running",
  published: "Published",
  experimental: "Experimental (baseline shown)",
  refused: "Refused",
};

export function statusLabel(status: string): string {
  return STATUS_LABELS[status] ?? status;
}

export function statusKind(status: string): "complete" | "partial" | "neutral" {
  if (status === "published") return "complete";
  if (status === "experimental" || status === "refused") return "partial";
  return "neutral";
}

export function formatMetric(value: unknown, digits = 3): string {
  return typeof value === "number" && Number.isFinite(value)
    ? value.toFixed(digits)
    : "—";
}
