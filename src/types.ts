export type Workload = "light" | "medium" | "heavy";

export interface AdvisorSettings {
  device_override: string;
  stack_overrides: Record<string, string>;
  source_deckverified: boolean;
  workload: Workload;
  update_check: boolean;
  remove_data_on_uninstall: boolean;
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
  compat: { proton: string | null; launch_options: string | null };
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
  source: { cached: boolean; error: { message: string } | null; fetched_at: number | null; enabled: boolean };
  recommendations: Recommendation[];
  update: { current: string; latest: string | null; available: boolean; install_url: string | null } | null;
}
