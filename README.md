# Tuning Advisor

A Decky Loader plugin. It detects your game, handheld and tuning tools, then recommends settings from community reports. **It never changes anything.** You apply each setting yourself.

- Detects the running game, or lets you pick a recent one.
- Detects the device from its DMI strings. Unknown devices get a generic profile.
- Detects installed tuning tools: SimpleDeckyTDP, PowerControl, PowerTools, LeGoTDP, Legion Go 2 Companion, Handheld Daemon, PowerStation, Decky LSFG-VK, OptiScaler and Fantastic, plus Steam's own TDP limit on SteamOS.
- Warns when two power tools will fight, and when LeGoTDP will undo Steam's TDP limit.
- Ranks Deck Verified reports by how close the reporting device is to yours, then by date, then by votes. Cycle through them with Previous and Next.
- Phrases power advice in your tool's own words, for example "Set TDP (Watts) to 15 in SimpleDeckyTDP."
- Checks every recommendation against your device: clamps TDP to its range, drops refresh rates the screen cannot show, and flags frame caps that will stutter.
- Never recommends FSR 4, which is not officially available on handheld chips under Proton.
- Falls back to general guidance for light, medium or heavy games when there is no report.

Issues and source: [breakmylegs/decky-plugins](https://github.com/breakmylegs/decky-plugins).

## Install

1. Decky Settings, General, turn on Developer mode.
2. Decky Settings, Developer, Install Plugin from URL, then enter the zip URL from the latest release.

## Supported devices

Steam Deck LCD and OLED, ROG Ally (Z1 and Z1 Extreme), ROG Ally X, ROG Xbox Ally, ROG Xbox Ally X, Legion Go, Legion Go S (Z2 Go and Z1 Extreme), Legion Go 2 (Z2 and Z2 Extreme), MSI Claw A8, Claw A1M, Claw 7 AI+ and Claw 8 AI+. Entries marked unverified in `registry/devices.json` still need checking against the maker's spec page.

Any other handheld gets a generic profile. To add one, run `tools/capture_device.sh` in Desktop Mode and attach the output to a pull request that adds an entry to `registry/devices.json`.

## Data and privacy

- Device facts come from `/sys/class/dmi/id/`, `/proc/cpuinfo` and `/etc/os-release`. Serial numbers and UUIDs are never read.
- Tools are detected by reading other plugins' `plugin.json` files and checking whether some files exist. Nothing is written to them.
- The game's Steam app ID is sent to deckverified.games. Non-Steam games are looked up by name. Replies are cached for 7 days and shown, marked as cached, when you are offline. Turn the source off in settings.
- Once a day it checks GitHub for a newer release. Turn that off in settings.

## Sources

Community reports from [Deck Verified](https://deckverified.games) by DeckSettings, GPL-3.0. Each recommendation links to its report. Device match strings from [Handheld Daemon](https://github.com/hhd-dev/hhd), [InputPlumber](https://github.com/ShadowBlip/InputPlumber) and Valve's steamos-manager.

## Licence

GPL-3.0. See `LICENSE`.
