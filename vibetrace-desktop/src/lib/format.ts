// Formatting helpers shared across the app.
// Note: missing values render as "n/a" rather than an em-dash, per the
// typography rules (em-dashes are banned as a design crutch).

export function fmtDuration(ms: number | null | undefined): string {
  if (!ms) return "n/a";
  if (ms < 1000) return `${ms.toFixed(0)}ms`;
  if (ms < 60000) return `${(ms / 1000).toFixed(2)}s`;
  return `${(ms / 60000).toFixed(2)}min`;
}

export function fmtCost(c: number | null | undefined): string {
  if (!c) return "$0.00";
  if (c < 0.01) return `$${c.toFixed(4)}`;
  return `$${c.toFixed(2)}`;
}

export function fmtTime(iso: string): string {
  const d = new Date(iso);
  return d.toLocaleTimeString();
}

export function fmtTokenCount(n: number): string {
  return n.toLocaleString();
}
