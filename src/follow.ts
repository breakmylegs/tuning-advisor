// Follow each running game once. After that a game the player picks stands,
// until another game starts.
export interface Follower {
  started(appid: number): void;
  stopped(): void;
  shouldFollow(playing: number | null): boolean;
}

export function makeFollower(): Follower {
  let followed: number | null = null;
  return {
    started(appid) {
      followed = appid;
    },
    stopped() {
      followed = null;
    },
    shouldFollow(playing) {
      if (playing === null || playing === followed) return false;
      followed = playing;
      return true;
    },
  };
}
