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
- Shows the Proton version and launch options from each report, by the exact name Steam uses, and where to set them. Shows your current values next to them.
- Keeps your own launch option wrappers, such as `~/lsfg %command%`, in a combined suggestion and explains each change.
- Flags launch options that run a command before the game or use shell operators. Never runs or applies any of them.
- Copy to clipboard where Game Mode allows it. If it does not, the text stays on screen to type.
- Optional AI recommendation with your own OpenAI, Anthropic or Google Gemini API key. Off until you set it up, and sent only when you press Generate. The reply is labelled "AI generated, unverified", shown next to the community reports, checked against your device, and never applied. Anything out of range is discarded and listed.

Issues and source: [breakmylegs/decky-plugins](https://github.com/breakmylegs/decky-plugins).

## Install

1. Decky Settings, General, turn on Developer mode.
2. Decky Settings, Developer, Install Plugin from URL, then enter the zip URL from the latest release.

## Supported devices

Steam Deck LCD and OLED, ROG Ally (Z1 and Z1 Extreme), ROG Ally X, ROG Xbox Ally, ROG Xbox Ally X, Legion Go, Legion Go S (Z2 Go and Z1 Extreme), Legion Go 2 (Z2 and Z2 Extreme), MSI Claw A8, Claw A1M, Claw 7 AI+ and Claw 8 AI+. Entries marked unverified in `registry/devices.json` still need checking against the maker's spec page.

Any other handheld gets a generic profile. To add one, run `tools/capture_device.sh` in Desktop Mode and attach the output to a pull request that adds an entry to `registry/devices.json`.

## AI setup (optional)

1. Show settings, then enter a key for one provider, or put it in `~/Documents/decky-import/tuning-advisor.json` and press Import keys from file:

```json
{ "anthropic_api_key": "your key", "ai_provider": "anthropic" }
```

The key names are `openai_api_key`, `anthropic_api_key` and `gemini_api_key`. Delete the file when asked.

2. In AI recommendation, pick the provider, press Load model list, pick a model, then Generate AI recommendation.

Use a dedicated key with a spending limit. Set a daily request limit in settings if you want one.

## Data and privacy

- Device facts come from `/sys/class/dmi/id/`, `/proc/cpuinfo` and `/etc/os-release`. Serial numbers and UUIDs are never read.
- Your current launch options and compatibility tool are read from the Steam client to show and merge. They stay on the device and are never changed.
- Tools are detected by reading other plugins' `plugin.json` files and checking whether some files exist. Nothing is written to them.
- AI requests, only when you press Generate, send the game name, app ID, device profile, your selected tools and short report excerpts to the provider you picked. No host names, user identifiers or other keys.
- The game's Steam app ID is sent to deckverified.games. Non-Steam games are looked up by name. Replies are cached for 7 days and shown, marked as cached, when you are offline. Turn the source off in settings.
- Once a day it checks GitHub for a newer release. Turn that off in settings.

## Sources

Community reports from [Deck Verified](https://deckverified.games) by DeckSettings, GPL-3.0. Each recommendation links to its report. Device match strings from [Handheld Daemon](https://github.com/hhd-dev/hhd), [InputPlumber](https://github.com/ShadowBlip/InputPlumber) and Valve's steamos-manager.

## Licence

GPL-3.0. See `LICENSE`.
