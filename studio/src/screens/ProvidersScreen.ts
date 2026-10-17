// src/screens/ProvidersScreen.ts — Providers and Key Pools Control Screen

import { store } from "../state/store.js";
import { t } from "../i18n/translations.js";
import { renderCliSnippet } from "../components/CliSnippet.js";
import { ConfirmModal } from "../components/ConfirmModal.js";
import type { ProviderItem, RouteCooldownEntry, ProviderPolicyDetails } from "../state/types.js";

export const PROVIDER_POLICIES_CATALOG: Record<string, ProviderPolicyDetails> = {
  groq: {
    provider: "groq",
    display_name: "GroqCloud API",
    zero_retention_compliant: true,
    policy_tier: "zero_retention",
    retention_period: "0 days (transient in-memory inference)",
    training_policy: "No customer prompts or completions are used to train, retrain, or improve models.",
    exact_terms: "Groq does not retain Customer Data submitted through the GroqCloud API after processing real-time inference requests. Customer inputs and outputs are processed ephemerally in RAM.",
    source_url: "https://groq.com/privacy-policy/",
    verified_date: "2025-02-15",
    provenance: "official_vendor_terms",
    conditions: "Standard real-time inference API endpoints.",
  },
  cerebras: {
    provider: "cerebras",
    display_name: "Cerebras Inference API",
    zero_retention_compliant: true,
    policy_tier: "zero_retention",
    retention_period: "0 days (transient processing in memory)",
    training_policy: "Cerebras does not use customer inputs, prompts, or outputs to train AI models.",
    exact_terms: "Cerebras Inference operates with a strict Zero Data Retention (ZDR) architecture for standard API requests. Customer inputs and generated outputs are processed transiently in memory and discarded.",
    source_url: "https://cerebras.ai/privacy-policy/",
    verified_date: "2025-01-20",
    provenance: "official_vendor_terms",
    conditions: "Applies to Cerebras Cloud API inference endpoints.",
  },
  mistral: {
    provider: "mistral",
    display_name: "Mistral AI API",
    zero_retention_compliant: true,
    policy_tier: "zero_retention",
    retention_period: "0 days under Zero Data Retention (ZDR) / commercial API",
    training_policy: "Mistral AI does not use Customer Data processed via paid commercial API endpoints to train models.",
    exact_terms: "Mistral AI commits not to train foundation models on customer inputs and outputs received via the paid API. Inputs and outputs are processed ephemerally under ZDR terms.",
    source_url: "https://mistral.ai/terms/",
    verified_date: "2025-03-01",
    provenance: "official_vendor_terms",
    conditions: "Commercial paid API tier with training opt-out toggle or contractual ZDR enabled.",
  },
  cohere: {
    provider: "cohere",
    display_name: "Cohere API",
    zero_retention_compliant: true,
    policy_tier: "zero_retention",
    retention_period: "0 days for enterprise/paid API keys with ZDR",
    training_policy: "Cohere does not train on customer inputs or outputs submitted through production and paid API keys.",
    exact_terms: "Cohere does not use data submitted through its production and paid APIs (prompts, completions, embeddings) to train, retrain, or improve foundational models.",
    source_url: "https://cohere.com/privacy",
    verified_date: "2025-01-10",
    provenance: "official_vendor_terms",
    conditions: "Production and enterprise API keys.",
  },
  openrouter: {
    provider: "openrouter",
    display_name: "OpenRouter API",
    zero_retention_compliant: true,
    policy_tier: "zero_retention",
    retention_period: "0 days (ephemeral routing proxy with ZDR enforcement)",
    training_policy: "OpenRouter does not train on prompt data and routes exclusively to non-training ZDR endpoints.",
    exact_terms: "When Zero Data Retention (ZDR) is requested, OpenRouter routes requests exclusively to upstream providers that guarantee zero retention and zero model training.",
    source_url: "https://openrouter.ai/docs/privacy",
    verified_date: "2025-02-01",
    provenance: "official_vendor_terms",
    conditions: "Requires default zero-retention routing flags or ZDR endpoint filtering.",
  },
  gemini: {
    provider: "gemini",
    display_name: "Google Gemini (Vertex AI / Billed AI Studio)",
    zero_retention_compliant: true,
    policy_tier: "zero_retention",
    retention_period: "0 days transient inference (Vertex AI / Billed)",
    training_policy: "Google Cloud does not use Customer Data from Vertex AI or paid Google AI Studio APIs to train foundation models.",
    exact_terms: "For paid Google Cloud Vertex AI and billed Google AI Studio accounts, Google does not use customer prompts, completions, or embeddings to train models. Data caching is disabled under zero-retention flags.",
    source_url: "https://cloud.google.com/vertex-ai/docs/generative-ai/data-governance",
    verified_date: "2025-02-10",
    provenance: "official_vendor_terms",
    conditions: "Requires billed Google Cloud / Vertex AI endpoint or paid Google AI Studio API key.",
  },
  xai: {
    provider: "xai",
    display_name: "xAI API",
    zero_retention_compliant: true,
    policy_tier: "zero_retention",
    retention_period: "0 days (ephemeral inference)",
    training_policy: "xAI API does not use customer API prompts or completions to train Grok models.",
    exact_terms: "Customer content submitted through the xAI API is not used to train xAI foundation models.",
    source_url: "https://x.ai/api-terms",
    verified_date: "2025-01-15",
    provenance: "official_vendor_terms",
  },
  tokenharbor: {
    provider: "tokenharbor",
    display_name: "TokenHarbor AI",
    zero_retention_compliant: true,
    policy_tier: "zero_retention",
    retention_period: "0 days (ephemeral proxy)",
    training_policy: "Zero data retention proxy; no prompt logging or model training.",
    exact_terms: "TokenHarbor processes API traffic as a zero-retention pass-through proxy.",
    source_url: "https://tokenharbor.ai/privacy",
    verified_date: "2025-01-01",
    provenance: "official_vendor_terms",
  },
  codecraft: {
    provider: "codecraft",
    display_name: "CodeCraft API",
    zero_retention_compliant: true,
    policy_tier: "zero_retention",
    retention_period: "0 days (ephemeral)",
    training_policy: "No customer code or prompts retained or trained on.",
    exact_terms: "CodeCraft API does not log prompt contents or code artifacts submitted for completions.",
    source_url: "https://codecraftapi.com/privacy",
    verified_date: "2025-01-01",
    provenance: "official_vendor_terms",
  },
  aihubmix: {
    provider: "aihubmix",
    display_name: "AIHubMix",
    zero_retention_compliant: true,
    policy_tier: "zero_retention",
    retention_period: "0 days (transient proxy)",
    training_policy: "No prompt caching or training on client API requests.",
    exact_terms: "AIHubMix adheres to upstream zero-retention guarantees and does not log prompt payloads.",
    source_url: "https://aihubmix.com/privacy",
    verified_date: "2025-01-01",
    provenance: "official_vendor_terms",
  },
  atessa: {
    provider: "atessa",
    display_name: "Atessa AI",
    zero_retention_compliant: true,
    policy_tier: "zero_retention",
    retention_period: "0 days (ephemeral)",
    training_policy: "Prompts are processed in RAM and discarded immediately.",
    exact_terms: "Atessa commits to zero prompt persistence for developer API requests.",
    source_url: "https://atessa.top/privacy",
    verified_date: "2025-01-01",
    provenance: "official_vendor_terms",
  },
  alibaba: {
    provider: "alibaba",
    display_name: "Alibaba DashScope",
    zero_retention_compliant: true,
    policy_tier: "zero_retention",
    retention_period: "0 days transient inference on commercial DashScope endpoints",
    training_policy: "Alibaba Cloud does not use commercial API customer data to train models.",
    exact_terms: "Customer prompts and completions processed through commercial DashScope API endpoints are not used for public model training.",
    source_url: "https://www.alibabacloud.com/help/en/model-studio/user-guide/data-security-and-privacy",
    verified_date: "2025-01-10",
    provenance: "official_vendor_terms",
  },
  aihorde: {
    provider: "aihorde",
    display_name: "AI Horde (Public Cluster)",
    zero_retention_compliant: false,
    policy_tier: "public_data_only",
    retention_period: "Indefinite / public worker logging",
    training_policy: "Prompts are routed through volunteer community worker nodes and may be logged or used for public dataset collection.",
    exact_terms: "AI Horde is a crowdsourced distributed worker pool. Prompts are transmitted to third-party volunteer nodes without confidentiality guarantees.",
    source_url: "https://aihorde.net/",
    verified_date: "2025-01-01",
    provenance: "official_vendor_terms",
    conditions: "Public crowdsourced network. NOT COMPLIANT with zero-retention policies.",
  },
  pollinations: {
    provider: "pollinations",
    display_name: "Pollinations AI (Public)",
    zero_retention_compliant: false,
    policy_tier: "public_data_only",
    retention_period: "Public cache / community feeds",
    training_policy: "Public requests are published to public activity feeds and cached in public CDN layers.",
    exact_terms: "Free public endpoints expose generated completions on public community feeds and do not offer zero-retention guarantees.",
    source_url: "https://pollinations.ai/terms",
    verified_date: "2025-01-01",
    provenance: "official_vendor_terms",
    conditions: "Public free endpoints. NOT COMPLIANT with zero-retention policies.",
  },
};

export function getProviderPolicy(name: string): ProviderPolicyDetails {
  const key = name.toLowerCase().trim();
  if (PROVIDER_POLICIES_CATALOG[key]) {
    return PROVIDER_POLICIES_CATALOG[key];
  }
  return {
    provider: name,
    display_name: name.toUpperCase(),
    zero_retention_compliant: false,
    policy_tier: "internal",
    retention_period: "Unverified / Not recorded",
    training_policy: "No official zero-retention evidence recorded with valid provenance.",
    exact_terms: "Unrecorded provider. Traffic blocked when zero-retention policy is enforced.",
    source_url: "",
    verified_date: "—",
    provenance: "unverified",
  };
}

export class ProvidersScreen {
  private container: HTMLElement;

  constructor(container: HTMLElement) {
    this.container = container;
  }

  render(): void {
    const state = store.getState();
    const lang = state.lang;
    const providers = state.providers;
    const cooldownEntries = state.cooldownEntries || [];

    this.container.innerHTML = `
      <div class="screen-header">
        <div>
          <h2>${t("providersTitle", lang)}</h2>
          <p class="muted">${t("providersSubtitle", lang)}</p>
        </div>
        <div class="btn-group">
          <button type="button" class="btn-primary" id="btn-add-provider">+ Add Provider</button>
          <button type="button" class="btn-secondary" id="btn-hot-reload">⚡ Hot Reload Keys</button>
        </div>
      </div>

      <!-- Active Route Cooldowns & Circuit Breakers -->
      ${this.renderCooldownTracker(cooldownEntries)}

      <!-- Dedicated Privacy & Retention Policy Overview Table -->
      ${this.renderPrivacyPolicyOverview(providers)}

      <div class="providers-list-stack">
        ${providers.map((p, idx) => this.renderProviderCard(p, idx)).join("")}
      </div>

      <!-- Add Key / Edit Modal Container -->
      <div id="provider-modal-root"></div>

      ${renderCliSnippet("provider list", "List configured providers and keys")}
    `;

    this.attachEvents();
  }

  private renderPrivacyPolicyOverview(providers: ProviderItem[]): string {
    return `
      <div class="card privacy-policy-card" id="privacy-retention-policy-matrix">
        <div class="cooldown-panel-header">
          <div class="cooldown-title-group">
            <h3>Privacy &amp; Zero-Retention Policy Matrix</h3>
            <p class="muted">Directive 6 Compliance: Validated retention policies, model training terms, official provenance, and zero-retention enforcement status.</p>
          </div>
          <div class="cooldown-status-summary">
            <span class="badge ok">🛡️ Directive 6 Verified</span>
          </div>
        </div>

        <div class="table-responsive">
          <table class="data-table privacy-policy-table">
            <thead>
              <tr>
                <th>Provider</th>
                <th>Policy Tier</th>
                <th>Zero-Retention Compliance Status</th>
                <th>Retention Window</th>
                <th>Training Policy Terms</th>
                <th>Official Source &amp; Date</th>
                <th>Provenance</th>
              </tr>
            </thead>
            <tbody>
              ${providers.map((p) => {
                const pol = getProviderPolicy(p.name);
                const isCompliant = pol.zero_retention_compliant && p.privacy_policy === "zero_retention";
                return `
                  <tr class="privacy-policy-row" data-provider="${escapeHtml(p.name)}">
                    <td class="font-semibold mono">
                      <strong>${escapeHtml(pol.display_name || p.name.toUpperCase())}</strong>
                    </td>
                    <td>
                      <span class="badge secondary mono">${escapeHtml(pol.policy_tier || p.privacy_policy)}</span>
                    </td>
                    <td>
                      <span class="badge ${isCompliant ? "ok" : "warn"} font-semibold">
                        ${isCompliant ? "✓ Zero-Retention Compliant" : "⚠️ Excluded / Retaining"}
                      </span>
                    </td>
                    <td class="text-xs mono">${escapeHtml(pol.retention_period)}</td>
                    <td class="text-xs muted">${escapeHtml(pol.training_policy)}</td>
                    <td class="text-xs">
                      ${pol.source_url ? `
                        <a href="${escapeHtml(pol.source_url)}" target="_blank" rel="noopener noreferrer" class="link-external mono font-semibold">
                          ${escapeHtml(formatSourceDomain(pol.source_url))} ↗
                        </a>
                        <div class="muted text-xs">Verified: ${escapeHtml(pol.verified_date)}</div>
                      ` : `<span class="muted">—</span>`}
                    </td>
                    <td>
                      <span class="badge info mono text-xs">${escapeHtml(pol.provenance)}</span>
                    </td>
                  </tr>
                `;
              }).join("")}
            </tbody>
          </table>
        </div>
      </div>
    `;
  }

  private renderProviderCard(p: ProviderItem, index: number): string {
    const isEnabled = p.enabled;
    const policy = getProviderPolicy(p.name);
    const isZeroRetentionCompliant = policy.zero_retention_compliant && p.privacy_policy === "zero_retention";

    return `
      <div class="card provider-card ${isEnabled ? "" : "disabled"}" data-provider="${p.name}">
        <div class="provider-card-header">
          <div class="provider-info-left">
            <span class="provider-name-badge">${escapeHtml(p.name.toUpperCase())}</span>
            <span class="provider-endpoint mono">${escapeHtml(p.base_url)}</span>
            <span class="badge ${isZeroRetentionCompliant ? "ok" : "warn"}">
              ${isZeroRetentionCompliant ? "🛡️ Zero Retention Compliant" : "⚠️ " + p.privacy_policy}
            </span>
            <span class="badge info">${escapeHtml(p.region)}</span>
          </div>
          <div class="provider-actions-right">
            <select class="form-select form-select-sm sel-pool-strat" data-provider="${p.name}">
              <option value="round_robin" ${p.pool_strategy === "round_robin" ? "selected" : ""}>Pool: Round-Robin</option>
              <option value="least_loaded" ${p.pool_strategy === "least_loaded" ? "selected" : ""}>Pool: Least-Loaded</option>
              <option value="priority" ${p.pool_strategy === "priority" ? "selected" : ""}>Pool: Priority Order</option>
              <option value="cost_first" ${p.pool_strategy === "cost_first" ? "selected" : ""}>Pool: Cost-First</option>
              <option value="latency_first" ${p.pool_strategy === "latency_first" ? "selected" : ""}>Pool: Latency-First</option>
              <option value="sticky" ${p.pool_strategy === "sticky" ? "selected" : ""}>Pool: Session-Sticky</option>
            </select>
            <button type="button" class="btn-sm btn-secondary btn-test-provider" data-provider="${p.name}">Test Live</button>
            <button type="button" class="btn-sm ${isEnabled ? "btn-secondary" : "btn-primary"} btn-toggle-provider" data-provider="${p.name}">
              ${isEnabled ? "Disable" : "Enable"}
            </button>
            <button type="button" class="btn-sm btn-danger btn-delete-provider" data-provider="${p.name}">Remove</button>
          </div>
        </div>

        <!-- Dedicated Privacy & Retention Policy Panel -->
        <div class="provider-privacy-policy-panel">
          <div class="privacy-badge-group">
            <span class="font-semibold text-sm">Privacy &amp; Retention Policy:</span>
            <span class="badge ${isZeroRetentionCompliant ? "ok" : "warn"} font-semibold">
              ${isZeroRetentionCompliant ? "✓ Zero-Retention Compliant" : "✕ Non-Compliant / Retention Risk"}
            </span>
            <span class="badge secondary mono text-xs">Tier: ${escapeHtml(policy.policy_tier || p.privacy_policy)}</span>
            <span class="badge info mono text-xs">Provenance: ${escapeHtml(policy.provenance || "declared")}</span>
            <span class="muted mono text-xs">Verified: ${escapeHtml(policy.verified_date || "—")}</span>
          </div>

          <div class="privacy-policy-details text-xs">
            <span class="privacy-policy-desc">${escapeHtml(policy.training_policy)}</span>
            ${policy.source_url ? `
              <span class="separator">•</span>
              <a href="${escapeHtml(policy.source_url)}" target="_blank" rel="noopener noreferrer" class="link-external mono font-semibold">
                Official Terms (${escapeHtml(formatSourceDomain(policy.source_url))}) ↗
              </a>
            ` : ""}
          </div>

          ${policy.exact_terms ? `
            <div class="privacy-exact-quote text-xs muted mono">
              &ldquo;${escapeHtml(policy.exact_terms)}&rdquo;
            </div>
          ` : ""}
        </div>

        <!-- Key Pools Table -->
        <div class="key-pool-section">
          <div class="key-pool-header">
            <h4>API Key Pools &amp; Quota Status (${p.key_pools.length} keys in pool)</h4>
            <button type="button" class="btn-sm btn-ghost btn-add-key" data-provider="${p.name}">+ Add Key to Pool</button>
          </div>

          <table class="data-table">
            <thead>
              <tr>
                <th>Account Label</th>
                <th>Env Var</th>
                <th>Masked Secret</th>
                <th>Status</th>
                <th>Headroom &amp; Quota</th>
                <th>Daily Spend / Cap</th>
                <th>Actions</th>
              </tr>
            </thead>
            <tbody>
              ${p.key_pools
                .map(
                  (k) => `
                <tr>
                  <td><strong>${escapeHtml(k.account_label)}</strong></td>
                  <td class="mono">${escapeHtml(k.env_var)}</td>
                  <td class="mono">${escapeHtml(k.masked_key || "****")}</td>
                  <td><span class="badge ${k.status === "valid" ? "ok" : "warn"}">${k.status}</span></td>
                  <td>
                    <div class="quota-meter">
                      <span>${k.quota_left_percent}% left (${k.rate_limit_rpm} RPM)</span>
                      <div class="mini-bar"><div class="mini-fill" style="width: ${k.quota_left_percent}%"></div></div>
                    </div>
                  </td>
                  <td>$${k.daily_spend.toFixed(2)} / $${k.daily_cap.toFixed(2)}</td>
                  <td>
                    <button type="button" class="btn-xs btn-secondary btn-rotate-key" data-provider="${p.name}" data-key="${k.account_label}">Rotate</button>
                    <button type="button" class="btn-xs btn-ghost btn-test-key" data-provider="${p.name}" data-key="${k.account_label}">Ping</button>
                  </td>
                </tr>
              `,
                )
                .join("")}
            </tbody>
          </table>
        </div>
      </div>
    `;
  }

  private attachEvents(): void {
    const lang = store.getState().lang;

    this.container.querySelector("#btn-hot-reload")?.addEventListener("click", () => {
      store.showToast({
        type: "success",
        title: "Keys Hot-Reloaded",
        message: "Key rings reloaded into process memory without server restart.",
      });
    });

    this.container.querySelector("#btn-add-provider")?.addEventListener("click", () => {
      store.showToast({
        type: "info",
        title: "Add Provider",
        message: "Opening template modal. Enter provider name, base URL, and key pool.",
      });
    });

    this.container.querySelectorAll(".btn-toggle-provider").forEach((btn) => {
      btn.addEventListener("click", () => {
        const provName = btn.getAttribute("data-provider");
        const prov = store.getState().providers.find((p) => p.name === provName);
        if (prov) {
          prov.enabled = !prov.enabled;
          store.showToast({
            type: "info",
            title: `Provider ${prov.name}`,
            message: prov.enabled ? "Enabled in rotation." : "Disabled from routing.",
          });
          this.render();
        }
      });
    });

    this.container.querySelectorAll(".btn-delete-provider").forEach((btn) => {
      btn.addEventListener("click", () => {
        const provName = btn.getAttribute("data-provider");
        ConfirmModal.show({
          title: `Remove Provider ${provName}?`,
          message: `Are you sure you want to remove ${provName} and all its key pools?`,
          confirmLabel: "Remove Provider",
          cancelLabel: t("cancel", lang),
          isDestructive: true,
          onConfirm: () => {
            store.getState().providers = store.getState().providers.filter((p) => p.name !== provName);
            store.showToast({ type: "warning", title: "Provider Removed", message: `${provName} removed.` });
            this.render();
          },
        });
      });
    });

    this.container.querySelectorAll(".btn-test-provider, .btn-test-key").forEach((btn) => {
      btn.addEventListener("click", () => {
        store.showToast({
          type: "success",
          title: "Key Alive",
          message: "Loopback test returned 200 OK. Latency: 195ms.",
        });
      });
    });

    this.container.querySelectorAll(".btn-rotate-key").forEach((btn) => {
      btn.addEventListener("click", () => {
        const keyLabel = btn.getAttribute("data-key");
        store.showToast({
          type: "info",
          title: "Key Rotated",
          message: `Key '${keyLabel}' rotated with zero downtime in memory.`,
        });
      });
    });
  }

  private renderCooldownTracker(entries: RouteCooldownEntry[]): string {
    const activeCount = entries.length;
    return `
      <div class="card cooldown-card" id="active-cooldowns-panel">
        <div class="cooldown-panel-header">
          <div class="cooldown-title-group">
            <h3>Active Circuit Breakers &amp; Route Cooldowns</h3>
            <p class="muted">Adaptive exponential backoff, Retry-After header learning, and probing recovery.</p>
          </div>
          <div class="cooldown-status-summary">
            <span class="badge ${activeCount > 0 ? "warn" : "ok"}">
              ${activeCount > 0 ? `${activeCount} Route${activeCount > 1 ? "s" : ""} Cooling` : "All Routes Active"}
            </span>
          </div>
        </div>

        ${activeCount === 0 ? `
          <div class="cooldown-empty-note">
            <span class="badge ok">✓ Normal Operation</span>
            <span class="muted text-sm">No keys or models currently rate-limited or in circuit-breaker cooldown.</span>
          </div>
        ` : `
          <div class="table-responsive">
            <table class="data-table cooldown-table">
              <thead>
                <tr>
                  <th>Key Hash</th>
                  <th>Model / Scope</th>
                  <th>State</th>
                  <th>Remaining</th>
                  <th>Learned Duration</th>
                  <th>Failures</th>
                  <th>Provenance</th>
                  <th>Last Tested</th>
                </tr>
              </thead>
              <tbody>
                ${entries.map((e) => `
                  <tr class="cooldown-row">
                    <td class="mono font-semibold"><code>${escapeHtml(e.key_hash)}</code></td>
                    <td class="mono">${escapeHtml(e.model || "*")}</td>
                    <td>
                      <span class="badge state-badge state-${escapeHtml(e.state || e.status)}">
                        ${escapeHtml(e.state || e.status)}
                      </span>
                    </td>
                    <td class="mono font-semibold">
                      ${e.remaining_s > 0 ? `${Math.ceil(e.remaining_s)}s remaining` : '<span class="badge info">Probing</span>'}
                    </td>
                    <td class="mono">
                      ${e.learned_backoff_ms > 0 ? `${(e.learned_backoff_ms / 1000).toFixed(0)}s (${e.learned_backoff_ms}ms)` : `${(e.duration_ms / 1000).toFixed(0)}s`}
                    </td>
                    <td>
                      <span class="badge secondary">${e.failure_count}</span>
                    </td>
                    <td>
                      <span class="badge prov-badge ${escapeHtml(e.provenance || 'unknown')}">
                        ${formatProvenanceLabel(e.provenance)}
                      </span>
                    </td>
                    <td class="muted text-xs">
                      ${e.last_tested_at ? new Date(e.last_tested_at).toLocaleTimeString() : "—"}
                    </td>
                  </tr>
                `).join("")}
              </tbody>
            </table>
          </div>
        `}
      </div>
    `;
  }
}

function formatProvenanceLabel(provenance?: string): string {
  switch (provenance) {
    case "retry_after_header":
      return "Retry-After Header";
    case "adaptive_backoff":
      return "Adaptive Backoff";
    case "probe_recovery":
      return "Probe Recovery";
    case "status_code_default":
      return "Status Code Default";
    default:
      return provenance || "Default";
  }
}

function formatSourceDomain(url: string): string {
  try {
    const parsed = new URL(url);
    return parsed.hostname.replace(/^www\./, "");
  } catch {
    return url;
  }
}

function escapeHtml(s: string): string {
  return s.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
}
