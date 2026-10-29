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
- Shows what your own tools are set to for this game, next to the recommendation: SimpleDeckyTDP, PowerControl, LeGoTDP and Legion Go 2 Companion TDP, and your Decky LSFG-VK profile. Read only.
- Optional ProtonDB reports from handhelds, from a monthly index of ProtonDB's open data. Adds Proton versions, launch options and notes, with the share of reports that say the game works.
- Optional PCGamingWiki details with your own bot password: which upscalers and frame generation the game supports, and where it keeps config and save files. Flags a recommended upscaler the game does not list.
- Optional AI recommendation with your own OpenAI, Anthropic or Google Gemini API key. Off until you set it up, and sent only when you press Generate. The reply replaces the report cards while you view it, labelled "AI generated, unverified". Back to source reports returns to the community reports. It is checked against your device and never applied. Anything out of range is discarded and listed.

Issues and source: [breakmylegs/decky-plugins](https://github.com/breakmylegs/decky-plugins).

## Install

1. Decky Settings, General, turn on Developer mode.
2. Decky Settings, Developer, Install Plugin from URL, then enter the zip URL from the latest release.

Needs Decky Loader 3.0.4 or later. If you installed 0.5.0 or earlier, uninstall it first, then install this one. Your settings are kept.

## Updating

Open the plugin and scroll to Updates. It shows your version and what the last check found.

- **Check for updates** asks GitHub for the latest release now.
- **Update now** appears when a newer version is out. Confirm in Decky's prompt. Your settings and keys are kept.
- **Reinstall latest** appears otherwise, and installs the latest release again the same way.
- **Copy install link** copies the link for Decky Settings, Developer, Install Plugin from URL. The link is shown under it, in case copying is not available in Game Mode.

Leave "Remove settings on uninstall" off, because an update counts as an uninstall.

## Supported devices

Steam Deck LCD and OLED, ROG Ally (Z1 and Z1 Extreme), ROG Ally X, ROG Xbox Ally, ROG Xbox Ally X, Legion Go, Legion Go S (Z2 Go and Z1 Extreme), Legion Go 2 (Z2 and Z2 Extreme), MSI Claw A8, Claw A1M, Claw 7 AI+ and Claw 8 AI+. Entries marked unverified in `registry/devices.json` still need checking against the maker's spec page.

Any other handheld gets a generic profile. To add one, run `tools/capture_device.sh` in Desktop Mode and attach the output to a pull request that adds an entry to `registry/devices.json`.

## ProtonDB and PCGamingWiki (optional)

Both are off by default. Turn them on in settings.

- **ProtonDB** downloads a 2 MB index from GitHub once, then monthly. It holds the latest reports from Steam Decks and Ryzen Z1 and Z2 handhelds.
- **PCGamingWiki** needs a bot password. Sign in at pcgamingwiki.com, open Special:BotPasswords, create one with the grant "Create, query and delete data through the Cargo extension", then enter the bot user name (for example `YourName@advisor`) and password in settings.

## AI setup (optional)

1. Show settings, then enter a key for one provider, or put it in `~/Documents/decky-import/tuning-advisor.json` and press Import keys from file:

```json
{ "anthropic_api_key": "your key", "ai_provider": "anthropic" }
```

The key names are `openai_api_key`, `anthropic_api_key` and `gemini_api_key`. Delete the file when asked.

2. In AI setup at the bottom of the panel, pick the provider, press Load model list and pick a model.
3. Generate AI recommendation then appears near the top. Press it to see the AI values in the cards. Back to source reports switches back, and Show AI recommendation shows the last reply again without a new request.

Use a dedicated key with a spending limit. Set a daily request limit in settings if you want one.

## Data and privacy

- Device facts come from `/sys/class/dmi/id/`, `/proc/cpuinfo` and `/etc/os-release`. Serial numbers and UUIDs are never read.
- Your current launch options and compatibility tool are read from the Steam client to show and merge. They stay on the device and are never changed.
- Tools are detected by reading other plugins' `plugin.json` files and checking whether some files exist. Their settings files are read to show your current values. Nothing is written to them.
- AI requests, only when you press Generate, send the game name, app ID, device profile, your selected tools and short report excerpts to the provider you picked. No host names, user identifiers or other keys.
- The game's Steam app ID is sent to deckverified.games. Non-Steam games are looked up by name. Replies are cached for 7 days and shown, marked as cached, when you are offline. Turn the source off in settings.
- Once a day it checks GitHub for a newer release. Turn that off in settings.

## Sources

Community reports from [Deck Verified](https://deckverified.games) by DeckSettings, GPL-3.0. Each recommendation links to its report. Contains information from [ProtonDB](https://www.protondb.com), made available under the [ODbL](https://opendatacommons.org/licenses/odbl/). Game details from [PCGamingWiki](https://www.pcgamingwiki.com), CC BY-NC-SA. Device match strings from [Handheld Daemon](https://github.com/hhd-dev/hhd), [InputPlumber](https://github.com/ShadowBlip/InputPlumber) and Valve's steamos-manager.

## Licence

GPL-3.0. See `LICENSE`.
