import { describe, expect, it } from "vitest";
import { makeFollower } from "./follow";

describe("makeFollower", () => {
  it("follows a game that was running before the plugin loaded, once", () => {
    const f = makeFollower();
    expect(f.shouldFollow(42)).toBe(true);
    // The panel opens again after the player picked another game.
    expect(f.shouldFollow(42)).toBe(false);
  });

  it("does not replace a pick with a game the watcher already sent", () => {
    const f = makeFollower();
    f.started(42);
    expect(f.shouldFollow(42)).toBe(false);
  });

  it("follows the next game that starts", () => {
    const f = makeFollower();
    f.started(42);
    f.started(7);
    expect(f.shouldFollow(7)).toBe(false);
    f.stopped();
    expect(f.shouldFollow(9)).toBe(true);
  });

  it("does nothing with no game running", () => {
    expect(makeFollower().shouldFollow(null)).toBe(false);
  });
});
