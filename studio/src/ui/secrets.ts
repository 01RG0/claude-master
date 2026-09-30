/**
 * Mask API keys / secrets for display. Studio never stores raw secrets.
 */

const SECRETISH =
  /^(sk-|api[_-]?key|key_|tok_|bearer\s)/i;

export function maskSecret(value: string, visibleTail = 4): string {
  if (!value) return "";
  const trimmed = value.trim();
  if (trimmed.length <= visibleTail) {
    return "*".repeat(Math.max(4, trimmed.length));
  }
  const tail = trimmed.slice(-visibleTail);
  const prefix = trimmed.slice(0, Math.min(3, trimmed.length - visibleTail));
  return `${prefix}${"*".repeat(8)}${tail}`;
}

/** Reject attempts to persist raw secrets into localStorage / memory maps. */
export function assertNoSecretStorage(key: string, value: unknown): void {
  if (typeof value !== "string") return;
  if (SECRETISH.test(value) && !value.includes("*")) {
    throw new Error(`Refusing to store unmasked secret for key "${key}"`);
  }
}

export function maskProviderKeys(masks: string[] | undefined): string[] {
  if (!masks) return [];
  return masks.map((m) => (m.includes("*") ? m : maskSecret(m)));
}
