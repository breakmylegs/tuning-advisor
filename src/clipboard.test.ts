import { describe, expect, it } from "vitest";
import { copyText } from "./clipboard";

describe("copyText", () => {
  it("uses navigator.clipboard when it works", async () => {
    let got = "";
    const ok = await copyText("PROTON_LOG=1 %command%", {
      writeText: async (t) => {
        got = t;
      },
      execCopy: () => false,
    });
    expect(ok).toBe(true);
    expect(got).toBe("PROTON_LOG=1 %command%");
  });

  it("falls back to execCommand when the async API is refused", async () => {
    let fallback = "";
    const ok = await copyText("x", {
      writeText: async () => {
        throw new Error("NotAllowedError");
      },
      execCopy: (t) => {
        fallback = t;
        return true;
      },
    });
    expect(ok).toBe(true);
    expect(fallback).toBe("x");
  });

  it("reports failure when nothing works", async () => {
    expect(await copyText("x", {})).toBe(false);
    expect(await copyText("x", { execCopy: () => false })).toBe(false);
  });
});
