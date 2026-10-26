import { describe, expect, it } from "vitest";
import type { Recommendation, View } from "./types";
import { cycleLabel, deviceLine, gameTitle, groups, linkOuts, matchNote, shortDate, sourceLine, stackSummary } from "./view";

const rec: Recommendation = {
  source: "deckverified",
  source_url: "https://github.com/DeckSettings/game-reports-steamos/issues/1",
  report_title: "Report 1",
  report_date: "2026-01-10T19:19:46Z",
  votes: 1,
  device_reported: "Lenovo Legion Go S",
  device_match: "family",
  confidence: "medium",
  power: { tdp_w: 15, gpu_clock_mhz: null },
  display: { refresh_hz: null, fps_cap: 60, vrr: true },
  scaling: { steam_filter: "Linear", game_resolution: null },
  upscaler: { name: null, mode: null },
  frame_gen: { tool: null, mode: null },
  in_game: { preset: "Custom", settings: [{ name: "Texture Quality", value: "High" }] },
  compat: { proton: null, launch_options: null },
  notes: "",
  flags: [],
  lines: {
    power: ["Set TDP (Watts) to 15 in SimpleDeckyTDP."],
    display: ["Set Framerate Limit to 60 in Steam, Performance."],
    scaling: [],
    frame_gen: [],
    in_game: ["Graphics preset: Custom."],
  },
};

const view = {
  device: { id: "lenovo-legion-go-2-z2e", name: "Lenovo Legion Go 2", apu: "AMD Ryzen Z2 Extreme", how: "detected", generic: false },
  stack: {
    categories: ["power", "framegen", "upscaler", "fan"],
    selected: { power: "simpledeckytdp", framegen: "none" },
    names: { simpledeckytdp: "SimpleDeckyTDP" },
  },
} as unknown as View;

describe("advisor view", () => {
  it("builds the source line", () => {
    expect(sourceLine(rec, false)).toBe("Deck Verified | reported on Lenovo Legion Go S | 10 Jan 2026 | +1 votes | medium confidence");
    expect(sourceLine(rec, true)).toContain("| cached");
    expect(sourceLine({ ...rec, source: "fallback" }, false)).toBe("General guidance, not game-specific");
  });

  it("labels reports from other devices", () => {
    expect(matchNote(rec)).toBe("Reported on the same device family. Values are shown as reported.");
    expect(matchNote({ ...rec, device_match: "exact" })).toBe("Reported on your device.");
  });

  it("groups lines and drops empty groups", () => {
    const g = groups(rec);
    expect(g.map((x) => x.title)).toEqual(["Power", "Display", "In-game"]);
    expect(g[2].lines).toEqual(["Graphics preset: Custom.", "Texture Quality: High"]);
  });

  it("summarises device and stack", () => {
    expect(deviceLine(view)).toBe("Lenovo Legion Go 2 (AMD Ryzen Z2 Extreme)");
    expect(deviceLine({ ...view, device: { ...view.device, generic: true } })).toBe("Generic profile (AMD Ryzen Z2 Extreme)");
    expect(stackSummary(view)).toBe("Power: SimpleDeckyTDP. Frame generation: none");
  });

  it("builds link-outs by app ID or by name", () => {
    const steam = linkOuts({ appid: 1091500, shortcut_appid: null, name: "Cyberpunk 2077", build_id: null, shortcut: false });
    expect(steam[0].url).toBe("https://www.protondb.com/app/1091500");
    const shortcut = linkOuts({ appid: null, shortcut_appid: 3000000000, name: "A Game", build_id: null, shortcut: true });
    expect(shortcut[0].url).toBe("https://www.protondb.com/search?q=A%20Game");
    expect(linkOuts(null)).toEqual([]);
  });

  it("formats small things", () => {
    expect(gameTitle(null)).toBe("No game selected");
    expect(cycleLabel(0, 1)).toBe("");
    expect(cycleLabel(1, 7)).toBe("Report 2 of 7");
    expect(shortDate("nonsense")).toBe("");
  });
});
