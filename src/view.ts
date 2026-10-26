// Pure display logic for the advisor panel. Tested with vitest.
import type { AiResult, Game, ProtonSection, Recommendation, View } from "./types";

export const MATCH_LABELS: Record<string, string> = {
  exact: "your device",
  variant: "another variant of your device",
  family: "the same device family",
  same_apu: "a device with the same chip",
  other_handheld: "another handheld",
  steam_deck: "a Steam Deck",
  generic: "general guidance",
};

export const CATEGORY_LABELS: Record<string, string> = {
  power: "Power",
  framegen: "Frame generation",
  upscaler: "Upscaler",
  fan: "Fan",
};

export const GROUPS: { key: keyof Recommendation["lines"]; title: string }[] = [
  { key: "power", title: "Power" },
  { key: "display", title: "Display" },
  { key: "scaling", title: "Scaling and upscaler" },
  { key: "frame_gen", title: "Frame generation" },
  { key: "in_game", title: "In-game" },
];

const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

export function shortDate(iso: string): string {
  const d = new Date(iso);
  if (!iso || Number.isNaN(d.getTime())) return "";
  return `${d.getUTCDate()} ${MONTHS[d.getUTCMonth()]} ${d.getUTCFullYear()}`;
}

export function sourceLine(rec: Recommendation, cached: boolean): string {
  if (rec.source === "fallback") return "General guidance, not game-specific";
  const parts = ["Deck Verified"];
  if (rec.device_reported) parts.push(`reported on ${rec.device_reported}`);
  const date = shortDate(rec.report_date);
  if (date) parts.push(date);
  parts.push(`${rec.votes >= 0 ? "+" : ""}${rec.votes} votes`);
  parts.push(`${rec.confidence} confidence`);
  if (cached) parts.push("cached");
  return parts.join(" | ");
}

export function matchNote(rec: Recommendation): string {
  if (rec.source === "fallback") return "";
  if (rec.device_match === "exact") return "Reported on your device.";
  return `Reported on ${MATCH_LABELS[rec.device_match] ?? "another device"}. Values are shown as reported.`;
}

export function groups(rec: Recommendation): { title: string; lines: string[] }[] {
  const out = GROUPS.map((g) => ({ title: g.title, lines: [...(rec.lines[g.key] ?? [])] }));
  const inGame = out.find((g) => g.title === "In-game");
  if (inGame) for (const s of rec.in_game.settings.slice(0, 8)) inGame.lines.push(`${s.name}: ${s.value}`);
  return out.filter((g) => g.lines.length > 0);
}

export function deviceLine(view: View): string {
  if (view.device.generic) return `Generic profile (${view.device.apu || "unknown chip"})`;
  const how = view.device.how === "override" ? ", set in settings" : "";
  return `${view.device.name} (${view.device.apu})${how}`;
}

export function stackSummary(view: View): string {
  const parts = view.stack.categories
    .filter((c) => c === "power" || c === "framegen")
    .map((c) => {
      const id = view.stack.selected[c];
      const name = !id || id === "none" ? "none" : (view.stack.names[id] ?? id);
      return `${CATEGORY_LABELS[c] ?? c}: ${name}`;
    });
  return parts.join(". ");
}

export function gameTitle(game: Game | null): string {
  if (!game) return "No game selected";
  return game.shortcut ? `${game.name} (non-Steam)` : game.name;
}

export interface LinkOut {
  label: string;
  url: string;
}

export function linkOuts(game: Game | null): LinkOut[] {
  if (!game) return [];
  const q = encodeURIComponent(game.name);
  const links: LinkOut[] = [];
  if (game.appid) {
    links.push({ label: "ProtonDB", url: `https://www.protondb.com/app/${game.appid}` });
    links.push({ label: "PCGamingWiki", url: `https://www.pcgamingwiki.com/api/appid.php?appid=${game.appid}` });
  } else {
    links.push({ label: "ProtonDB", url: `https://www.protondb.com/search?q=${q}` });
    links.push({ label: "PCGamingWiki", url: `https://www.pcgamingwiki.com/w/index.php?search=${q}` });
  }
  links.push({ label: "SteamDeckHQ", url: `https://steamdeckhq.com/?s=${q}` });
  links.push({ label: "ShareDeck", url: "https://sharedeck.games/" });
  return links;
}

export function cycleLabel(index: number, total: number): string {
  return total > 1 ? `Report ${index + 1} of ${total}` : "";
}

export function optionLabel(view: View, id: string): string {
  if (id === "auto") return "Detected";
  if (id === "none") return "None";
  return view.stack.names[id] ?? id;
}

export function protonLine(p: ProtonSection): string {
  const status = p.matches ? "You already use this." : `You use ${p.current}.`;
  const build = p.build ? ` The report used build ${p.build}.` : "";
  return `${p.recommended}.${build} ${status}`;
}

export const SECRET_FOR: Record<string, string> = {
  openai: "openai_api_key",
  anthropic: "anthropic_api_key",
  gemini: "gemini_api_key",
};

export function aiStatus(result: AiResult | null): string {
  if (!result) return "";
  if (result.error) return result.error.message;
  const when = result.cached ? "From cache" : "Just now";
  return `${result.label}. ${when}, ${result.model}.`;
}

export function capLine(used: number, cap: number): string {
  return cap > 0 ? `${used} of ${cap} AI requests used today.` : `${used} AI requests today. No daily limit.`;
}

export function aiPrivacyLine(providerName: string): string {
  return `Sends the game name, app ID, device profile, your selected tools and short report excerpts to ${providerName}. Nothing else.`;
}
