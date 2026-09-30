/**
 * Gateway admin panel — displays MASKED keys only. Never stores secrets.
 */

import type { GatewayHealthData, GatewayProviderHealth } from "../types/events.js";
import { assertNoSecretStorage, maskProviderKeys, maskSecret } from "./secrets.js";

export interface MaskedKeyRow {
  provider: string;
  mask: string;
  state: "active" | "cooldown" | "unknown";
}

export class GatewayAdmin {
  private readonly root: HTMLElement;
  private health: GatewayHealthData | null = null;
  /** In-memory masked fingerprints only — never raw secrets. */
  private maskedKeys: MaskedKeyRow[] = [];

  constructor(root: HTMLElement) {
    this.root = root;
    this.render();
  }

  updateHealth(data: GatewayHealthData): void {
    this.health = data;
    const rows: MaskedKeyRow[] = [];
    for (const p of data.providers) {
      this.ingestProvider(p, rows);
    }
    this.maskedKeys = rows;
    this.render();
  }

  private ingestProvider(p: GatewayProviderHealth, rows: MaskedKeyRow[]): void {
    const masks = maskProviderKeys(p.key_masks);
    if (masks.length === 0) {
      // Synthesize opaque placeholders from counts — no secrets involved.
      for (let i = 0; i < p.active_keys; i++) {
        rows.push({
          provider: p.name,
          mask: maskSecret(`${p.name}-active-${i}-xxxx`),
          state: "active",
        });
      }
      for (let i = 0; i < p.cooldown_keys; i++) {
        rows.push({
          provider: p.name,
          mask: maskSecret(`${p.name}-cool-${i}-xxxx`),
          state: "cooldown",
        });
      }
      return;
    }
    masks.forEach((mask, i) => {
      assertNoSecretStorage(`gateway.${p.name}.key`, mask);
      rows.push({
        provider: p.name,
        mask,
        state: i < p.active_keys ? "active" : "cooldown",
      });
    });
  }

  /** Attempting to register a raw key must throw / mask — public API for tests. */
  registerKeyDisplay(provider: string, keyOrMask: string, state: MaskedKeyRow["state"]): void {
    const mask = keyOrMask.includes("*") ? keyOrMask : maskSecret(keyOrMask);
    assertNoSecretStorage(`gateway.${provider}.key`, mask);
    this.maskedKeys.push({ provider, mask, state });
    this.render();
  }

  getMaskedKeys(): readonly MaskedKeyRow[] {
    return this.maskedKeys;
  }

  private render(): void {
    const h = this.health;
    const providers =
      h?.providers
        .map(
          (p) =>
            `<tr>
              <td>${escape(p.name)}</td>
              <td>${p.active_keys}</td>
              <td>${p.cooldown_keys}</td>
            </tr>`,
        )
        .join("") ?? "";

    const keys = this.maskedKeys
      .map(
        (k) =>
          `<tr>
            <td>${escape(k.provider)}</td>
            <td class="mono">${escape(k.mask)}</td>
            <td><span class="badge ${k.state}">${k.state}</span></td>
          </tr>`,
      )
      .join("");

    this.root.innerHTML = `
      <header>Gateway admin</header>
      <p class="muted">Keys shown MASKED only · never stored as secrets · req/60s: ${
        h?.requests_last_60s ?? "—"
      }</p>
      <h3>Providers</h3>
      <table>
        <thead><tr><th>Name</th><th>Active</th><th>Cooldown</th></tr></thead>
        <tbody>${providers || '<tr><td colspan="3" class="muted">Waiting for gateway_health…</td></tr>'}</tbody>
      </table>
      <h3>Keys (masked)</h3>
      <table>
        <thead><tr><th>Provider</th><th>Mask</th><th>State</th></tr></thead>
        <tbody>${keys || '<tr><td colspan="3" class="muted">None</td></tr>'}</tbody>
      </table>
    `;
  }
}

function escape(s: string): string {
  return s.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
}
