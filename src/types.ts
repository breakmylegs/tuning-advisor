export type Workload = "light" | "medium" | "heavy";

export interface AdvisorSettings {
  device_override: string;
  stack_overrides: Record<string, string>;
  source_deckverified: boolean;
  workload: Workload;
  update_check: boolean;
  remove_data_on_uninstall: boolean;
  ai_provider: "" | "openai" | "anthropic" | "gemini";
  ai_model: string;
  ai_daily_cap: number;
  source_protondb: boolean;
  source_pcgw: boolean;
  pcgw_username: string;
}

export interface ProtonDbState {
  enabled: boolean;
  error: { kind: string; message: string; detail?: string } | null;
  dump: string | null;
  summary: { reports: number; works: number; handheld: number; share: number | null; dump: string | null; attribution: string } | null;
}

export interface PcgwData {
  page: string;
  url: string;
  upscaling: string[];
  frame_gen: string[];
  hdr: string | null;
  ray_tracing: string | null;
  ultrawide: string | null;
  files: { type: string; platform: string; paths: string[] }[];
  attribution: string;
}

export interface CurrentValues {
  power: { tool: string; tdp_w: number | null; scope: string; preset?: string | null; note: string | null } | null;
  framegen: {
    tool: string;
    profile: string | null;
    multiplier: number | null;
    flow_scale: number | null;
    performance_mode: boolean | null;
  } | null;
}

export interface PcgwState {
  enabled: boolean;
  error: { kind: string; message: string; detail?: string } | null;
  cached: boolean;
  has_password: boolean;
  data: PcgwData | null;
}

export interface AiProviderView {
  id: "openai" | "anthropic" | "gemini";
  name: string;
  key: { set: boolean; masked: string };
}

export interface AiResult {
  label: string;
  provider: string;
  model: string;
  cached: boolean;
  rec: Recommendation | null;
  discarded: string[];
  error: { kind: string; message: string; detail?: string } | null;
  generated_at: number | null;
}

export interface LaunchSection {
  recommended: string;
  current: string;
  where: string;
  flags: string[];
  merged: string | null;
  merge_notes: string[];
  same_as_current: boolean;
}

export interface ProtonSection {
  recommended: string;
  force: boolean;
  build: string | null;
  install_note: string | null;
  current: string;
  matches: boolean;
  where: string;
  as_reported: string;
}

export interface CompatSection {
  proton: ProtonSection | null;
  launch: LaunchSection | null;
}

export interface Recommendation {
  source: "deckverified" | "protondb" | "pcgw" | "fallback" | "ai";
  source_url: string;
  report_title?: string;
  report_date: string;
  votes: number;
  device_reported: string;
  device_match: string;
  confidence: "high" | "medium" | "low";
  workload?: Workload;
  power: { tdp_w: number | null; gpu_clock_mhz: number | null };
  display: { refresh_hz: number | null; fps_cap: number | null; vrr: boolean | null };
  scaling: { steam_filter: string | null; scaling_mode?: string | null; game_resolution: string | null };
  upscaler: { name: string | null; mode: string | null };
  frame_gen: { tool: string | null; mode: string | null; requires?: string };
  in_game: { preset: string | null; settings: { name: string; value: string }[] };
  compat: { proton: string | null; tool: string | null; tool_version: string | null; launch_options: string | null };
  compat_section?: CompatSection | null;
  rating?: string | null;
  target_fps?: string | null;
  notes: string;
  flags: string[];
  lines: Record<"power" | "display" | "scaling" | "frame_gen" | "in_game", string[]>;
}

export interface Game {
  appid: number | null;
  shortcut_appid: number | null;
  name: string;
  build_id: number | null;
  shortcut: boolean;
}

export interface View {
  version: string;
  settings: AdvisorSettings;
  device: {
    id: string;
    name: string;
    apu: string;
    how: "detected" | "override" | "generic";
    generic: boolean;
    verified: boolean;
    facts: Record<string, string>;
  };
  devices: { id: string; name: string }[];
  os: { id: string; pretty: string; version: string };
  stack: {
    detected: { id: string; disabled?: boolean }[];
    selected: Record<string, string>;
    names: Record<string, string>;
    categories: string[];
    options: Record<string, string[]>;
  };
  conflicts: { kind: string; text: string }[];
  game: Game | null;
  source: { cached: boolean; error: { message: string; detail?: string } | null; fetched_at: number | null; enabled: boolean };
  current: CurrentValues;
  protondb: ProtonDbState;
  pcgw: PcgwState;
  recommendations: Recommendation[];
  update: { current: string; latest: string | null; available: boolean; install_url: string | null } | null;
  ai: { providers: AiProviderView[]; used_today: number; result: AiResult | null };
  import_path: string;
}
