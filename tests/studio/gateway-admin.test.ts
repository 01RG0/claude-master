import { describe, expect, it } from "vitest";
import { maskSecret, assertNoSecretStorage } from "../../studio/src/ui/secrets";
import { GatewayAdmin } from "../../studio/src/ui/gateway-admin";

describe("secrets / gateway admin", () => {
  it("masks raw keys", () => {
    const m = maskSecret("sk-abcdefghijklmnopqrstuvwxyz");
    expect(m).toContain("*");
    expect(m).not.toContain("abcdefghijklmnopqrst");
    expect(m.endsWith("wxyz")).toBe(true);
  });

  it("assertNoSecretStorage rejects unmasked secrets", () => {
    expect(() => assertNoSecretStorage("k", "sk-live-secret-value-here")).toThrow(
      /unmasked secret/,
    );
    expect(() => assertNoSecretStorage("k", "sk-********abcd")).not.toThrow();
  });

  it("GatewayAdmin only retains masked keys", () => {
    const root = document.createElement("div");
    const admin = new GatewayAdmin(root);
    admin.registerKeyDisplay("groq", "sk-super-secret-key-9999", "active");
    const keys = admin.getMaskedKeys();
    expect(keys).toHaveLength(1);
    expect(keys[0]!.mask).toContain("*");
    expect(keys[0]!.mask).not.toContain("super-secret");
    admin.updateHealth({
      providers: [
        { name: "groq", active_keys: 2, cooldown_keys: 1, key_masks: ["grq********aa01"] },
      ],
      requests_last_60s: 3,
    });
    for (const k of admin.getMaskedKeys()) {
      expect(k.mask.includes("*") || k.mask.length <= 12).toBe(true);
      expect(k.mask.startsWith("sk-super")).toBe(false);
    }
  });
});
