import { describe, expect, it } from "vitest";
import type { Recommendation, View } from "./types";
import {
  aiPrivacyLine,
  aiStatus,
  capLine,
  currentLines,
  cycleLabel,
  deviceLine,
  gameTitle,
  groups,
  linkOuts,
  matchNote,
  pcgwLines,
  protondbLine,
  protonLine,
  shortDate,
  sourceLine,
  stackSummary,
} from "./view";

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
  compat: { proton: null, tool: null, tool_version: null, launch_options: null },
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

  it("describes the Proton recommendation", () => {
    const base = { force: true, build: null, install_note: null, where: "", as_reported: "" };
    expect(protonLine({ ...base, recommended: "Proton 9.0", build: "9.0-3", current: "Proton 9.0-4", matches: true })).toBe(
      "Proton 9.0. The report used build 9.0-3. You already use this.",
    );
    expect(protonLine({ ...base, recommended: "GE-Proton10-20", current: "Steam's default", matches: false })).toBe(
      "GE-Proton10-20. You use Steam's default.",
    );
  });

  it("labels AI output and the daily cap", () => {
    const base = {
      label: "AI generated, unverified",
      provider: "anthropic",
      model: "m1",
      cached: false,
      rec: null,
      discarded: [],
      error: null,
      generated_at: 1,
    };
    expect(aiStatus(base)).toBe("AI generated, unverified. Just now, m1.");
    expect(aiStatus({ ...base, cached: true })).toBe("AI generated, unverified. From cache, m1.");
    expect(aiStatus({ ...base, error: { kind: "auth", message: "Add your key." } })).toBe("Add your key.");
    expect(aiStatus(null)).toBe("");
    expect(capLine(2, 5)).toBe("2 of 5 AI requests used today.");
    expect(capLine(3, 0)).toBe("3 AI requests today. No daily limit.");
    expect(aiPrivacyLine("OpenAI")).toContain("to OpenAI. Nothing else.");
  });

  it("names each source and drops votes where there are none", () => {
    expect(sourceLine({ ...rec, source: "protondb", votes: 0 }, false)).toBe(
      "ProtonDB | reported on Lenovo Legion Go S | 10 Jan 2026 | medium confidence",
    );
  });

  it("summarises ProtonDB", () => {
    const base = { enabled: true, error: null, dump: "oct1_2026" };
    const summary = { reports: 40, works: 30, handheld: 3, share: 75, dump: "oct1_2026", attribution: "x" };
    expect(protondbLine({ ...base, summary })).toBe("ProtonDB (oct1_2026): 75% of 40 reports say it works. 3 from handhelds.");
    expect(protondbLine({ ...base, summary: null })).toBe("ProtonDB has no reports from handhelds for this game.");
    expect(protondbLine({ ...base, enabled: false, summary: null })).toBe("");
    expect(protondbLine({ ...base, summary: null, error: { kind: "offline", message: "No network." } })).toBe(
      "ProtonDB: No network.",
    );
  });

  it("lists PCGamingWiki features and files", () => {
    const groups = pcgwLines({
      page: "P",
      url: "u",
      upscaling: ["DLSS", "FSR 3.1"],
      frame_gen: [],
      hdr: "true",
      ray_tracing: "false",
      ultrawide: null,
      files: [{ type: "config", platform: "Windows", paths: ["a", "b"] }],
      attribution: "x",
    });
    expect(groups).toEqual([
      { title: "Graphics options", lines: ["Upscalers: DLSS, FSR 3.1", "Supports HDR"] },
      { title: "Config and save files", lines: ["config (Windows): a  or  b"] },
    ]);
  });

  it("compares current tool values with the recommendation", () => {
    const names = { legotdp: "LeGoTDP", "lsfg-vk": "Decky LSFG-VK" };
    const power = { tool: "legotdp", tdp_w: 18, scope: "this game's profile", preset: "Balanced", note: null };
    expect(currentLines({ power, framegen: null }, rec, names)).toEqual([
      "LeGoTDP, this game's profile: 18 W (Balanced). The recommendation is 15 W.",
    ]);
    expect(currentLines({ power: { ...power, tdp_w: 15, preset: null }, framegen: null }, rec, names)).toEqual([
      "LeGoTDP, this game's profile: 15 W. That matches.",
    ]);
    const fg = { tool: "lsfg-vk", profile: "Cyberpunk", multiplier: 3, flow_scale: 0.75, performance_mode: true };
    expect(currentLines({ power: null, framegen: fg }, rec, names)).toEqual([
      'Decky LSFG-VK profile "Cyberpunk": 3x, flow scale 0.75, performance mode.',
    ]);
    const none = { ...fg, profile: null, multiplier: null, flow_scale: null, performance_mode: null };
    expect(currentLines({ power: null, framegen: none }, { ...rec, frame_gen: { tool: "lsfg-vk", mode: null } }, names)).toEqual([
      "Decky LSFG-VK has no profile for this game yet.",
    ]);
    expect(currentLines({ power: null, framegen: null }, rec, names)).toEqual([]);
  });
});
