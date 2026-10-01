import { maskSecret, assertNoSecretStorage, maskProviderKeys }
  from "/home/rootuser/claude-master/studio/src/ui/secrets.ts";
const secret = "sk-" + "k".repeat(40);
const masked = maskSecret(secret);
let threw = false;
try { assertNoSecretStorage("gatewayKey", secret); } catch { threw = true; }
const providerMasks = maskProviderKeys([secret]);
console.log(JSON.stringify({
  masked, isSecret: masked === secret, maskedOk: masked.includes("*"),
  threw, providerMasked: providerMasks[0] !== secret && providerMasks[0].includes("*"),
}));
