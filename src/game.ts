// Read the running game and recent games from the Steam client. Read only.
import { Router } from "@decky/ui";

// EAppType.Shortcut in @decky/ui typings.
const SHORTCUT_TYPE = 1073741824;

export interface GameRef {
  appid: number;
  name: string;
  buildId: number | null;
  shortcut: boolean;
}

export function describeApp(appid: number): GameRef | null {
  try {
    const overview = window.appStore?.GetAppOverviewByAppID(appid);
    if (!overview) return null;
    const details = window.appDetailsStore?.GetAppDetails(appid);
    return {
      appid,
      name: overview.display_name || `App ${appid}`,
      buildId: details?.nBuildID || null,
      shortcut: overview.app_type === SHORTCUT_TYPE,
    };
  } catch {
    return null;
  }
}

export function runningGame(): GameRef | null {
  try {
    const app = Router.MainRunningApp;
    return app ? describeApp(Number(app.appid)) : null;
  } catch {
    return null;
  }
}

export function recentGames(limit = 15): GameRef[] {
  try {
    const ids: number[] = window.collectionStore?.recentAppsCollection?.m_rgApps ?? [];
    const games = ids
      .map((id) => ({ id, ref: describeApp(id), played: window.appStore?.GetAppOverviewByAppID(id)?.rt_last_time_played ?? 0 }))
      .filter((g) => g.ref !== null)
      .sort((a, b) => b.played - a.played)
      .slice(0, limit)
      .map((g) => g.ref as GameRef);
    return games;
  } catch {
    return [];
  }
}

// Calls onStart with the game each time one starts, and onStop when the last one stops.
export function watchGames(onStart: (game: GameRef) => void, onStop: () => void): () => void {
  const running = new Set<number>();
  let handle: { unregister(): void } | undefined;
  try {
    handle = window.SteamClient?.GameSessions?.RegisterForAppLifetimeNotifications((n) => {
      if (n.bRunning) {
        running.add(n.unAppID);
        const ref = describeApp(n.unAppID);
        if (ref) onStart(ref);
      } else {
        running.delete(n.unAppID);
        if (running.size === 0) onStop();
      }
    });
  } catch {
    handle = undefined;
  }
  return () => handle?.unregister();
}
