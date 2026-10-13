// src/components/CliSnippet.ts — Expert Mode CLI command assistant

import { store } from "../state/store.js";

export function renderCliSnippet(command: string, explanation?: string): string {
  const isExpert = store.getState().userMode === "expert";
  if (!isExpert) return "";

  const escapedCmd = command.replace(/"/g, "&quot;");
  return `
    <div class="cli-snippet" data-cmd="${escapedCmd}">
      <div class="cli-snippet-header">
        <span class="cli-badge">CLI EQUIVALENT</span>
        ${explanation ? `<span class="cli-explanation">${escapeHtml(explanation)}</span>` : ""}
        <button type="button" class="btn-copy-cli" onclick="navigator.clipboard.writeText('${escapedCmd}').then(() => { const b=this; b.innerText='Copied!'; setTimeout(()=>b.innerText='Copy', 2000); })">Copy</button>
      </div>
      <pre class="cli-code"><code>cm ${escapeHtml(command)}</code></pre>
    </div>
  `;
}

function escapeHtml(s: string): string {
  return s.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
}
