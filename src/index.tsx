import { callable, definePlugin } from "@decky/api";
import {
  ButtonItem,
  ConfirmModal,
  DropdownItem,
  Field,
  Focusable,
  DialogButton,
  Navigation,
  PanelSection,
  PanelSectionRow,
  TextField,
  ToggleField,
  showModal,
  staticClasses,
} from "@decky/ui";
import { useEffect, useState } from "react";
import { FaSlidersH } from "react-icons/fa";
import { UpdateBadge } from "./shared/UpdateBadge";
import { useBackendEvent } from "./shared/useBackendEvent";
import { copyText } from "./clipboard";
import { makeFollower } from "./follow";
import { currentCompat, recentGames, runningGame, watchGames, type GameRef } from "./game";
import type { AdvisorSettings, AiProviderView, CompatSection, View, Workload } from "./types";
import {
  SECRET_FOR,
  aiPrivacyLine,
  aiStatus,
  capLine,
  currentLines,
  pcgwLines,
  protondbLine,
  CATEGORY_LABELS,
  cycleLabel,
  deviceLine,
  gameTitle,
  groups,
  linkOuts,
  matchNote,
  optionLabel,
  protonLine,
  sourceLine,
  stackSummary,
} from "./view";

type Wrapped = { ok: boolean; view?: View; message?: string; error?: { message: string } };

const getView = callable<[], View>("get_view");
const setGame = callable<
  [appid: number, name: string, buildId: number | null, shortcut: boolean, launchOptions: string, compatTool: string],
  Wrapped
>("set_game");
const setCurrentCompat = callable<[launchOptions: string, compatTool: string], Wrapped>("set_current_compat");

async function sendGame(game: GameRef): Promise<Wrapped> {
  const current = await currentCompat(game.appid, game.shortcut);
  return setGame(game.appid, game.name, game.buildId, game.shortcut, current.launchOptions, current.compatTool);
}
const refresh = callable<[], Wrapped>("refresh");
const redetect = callable<[], Wrapped>("redetect");
const saveSettings = callable<[values: Partial<AdvisorSettings>], Wrapped>("save_settings");
const clearCache = callable<[], { ok: boolean; removed: number }>("clear_cache");
const setSecret = callable<[name: string, value: string], Wrapped>("set_secret");
const clearSecret = callable<[name: string], Wrapped>("clear_secret");
const listModels = callable<
  [provider: string],
  { ok: boolean; models?: { id: string; label: string }[]; error?: { message: string } }
>("list_models");
const generateAi = callable<[], Wrapped>("generate_ai");
const setPcgwPassword = callable<[value: string], Wrapped>("set_pcgw_password");
const importFromFile = callable<[], { ok: boolean; message?: string; imported?: string[]; path: string; view?: View }>(
  "import_from_file",
);
const deleteImportFile = callable<[], { ok: boolean; message?: string }>("delete_import_file");

const note: React.CSSProperties = { fontSize: 12, lineHeight: 1.35 };
const warn: React.CSSProperties = { ...note, padding: "6px 8px", borderRadius: 4, background: "#4f3a1f" };

// The last game the watcher saw, so the panel can pick it up when it opens.
let lastSeen: GameRef | null = null;
// Each running game is picked once, so a game the player picks is not replaced
// every time the panel opens.
const follower = makeFollower();

function open(url: string) {
  Navigation.NavigateToExternalWeb(url);
  Navigation.CloseSideMenus();
}

function RecommendationCard({
  view,
  index,
  setIndex,
  apply,
}: {
  view: View;
  index: number;
  setIndex: (i: number) => void;
  apply: (v: View | undefined) => void;
}) {
  const recs = view.recommendations;
  const rec = recs[Math.min(index, recs.length - 1)];
  if (!rec) return null;
  const save = async (values: Partial<AdvisorSettings>) => {
    apply((await saveSettings(values)).view);
  };
  return (
    <PanelSection title={rec.source === "fallback" ? "General guidance" : "Recommendation"}>
      <PanelSectionRow>
        <Field focusable bottomSeparator="none" label={<span style={note}>{sourceLine(rec, view.source.cached)}</span>}>
          <span style={note}>{matchNote(rec)}</span>
        </Field>
      </PanelSectionRow>
      {rec.source === "fallback" && (
        <PanelSectionRow>
          <DropdownItem
            label="Game load"
            rgOptions={[
              { data: "light", label: "Light" },
              { data: "medium", label: "Medium" },
              { data: "heavy", label: "Heavy" },
            ]}
            selectedOption={view.settings.workload}
            onChange={(o) => save({ workload: o.data as Workload })}
          />
        </PanelSectionRow>
      )}
      {groups(rec).map((g) => (
        <PanelSectionRow key={g.title}>
          <Field focusable bottomSeparator="none" label={g.title}>
            <div style={note}>
              {g.lines.map((line, i) => (
                <div key={i}>{line}</div>
              ))}
            </div>
          </Field>
        </PanelSectionRow>
      ))}
      {rec.flags.length > 0 && (
        <PanelSectionRow>
          <div style={warn}>
            {rec.flags.map((f, i) => (
              <div key={i}>{f}</div>
            ))}
          </div>
        </PanelSectionRow>
      )}
      {currentLines(view.current, rec, view.stack.names).length > 0 && (
        <PanelSectionRow>
          <Field focusable bottomSeparator="none" label="Your current settings">
            <div style={note}>
              {currentLines(view.current, rec, view.stack.names).map((line, i) => (
                <div key={i}>{line}</div>
              ))}
              <div style={{ marginTop: 2 }}>Read from your tools. Nothing is changed.</div>
            </div>
          </Field>
        </PanelSectionRow>
      )}
      {rec.source !== "fallback" && (rec.report_title || rec.notes) && (
        <PanelSectionRow>
          <Field focusable bottomSeparator="none" label="From the report">
            <div style={{ ...note, wordBreak: "break-word" }}>
              {rec.report_title && <div>{rec.report_title}</div>}
              {rec.notes && <div>{rec.notes}</div>}
            </div>
          </Field>
        </PanelSectionRow>
      )}
      {rec.source_url && (
        <PanelSectionRow>
          <ButtonItem layout="below" onClick={() => open(rec.source_url)}>
            Open this report
          </ButtonItem>
        </PanelSectionRow>
      )}
      {recs.length > 1 && (
        <PanelSectionRow>
          <Focusable style={{ display: "flex", gap: 8, alignItems: "center" }}>
            <DialogButton style={{ minWidth: 0, flex: 1 }} disabled={index === 0} onClick={() => setIndex(index - 1)}>
              Previous
            </DialogButton>
            <DialogButton
              style={{ minWidth: 0, flex: 1 }}
              disabled={index >= recs.length - 1}
              onClick={() => setIndex(index + 1)}
            >
              Next
            </DialogButton>
          </Focusable>
        </PanelSectionRow>
      )}
      {recs.length > 1 && (
        <PanelSectionRow>
          <div style={{ ...note, textAlign: "center" }}>{cycleLabel(index, recs.length)}</div>
        </PanelSectionRow>
      )}
    </PanelSection>
  );
}

const mono: React.CSSProperties = {
  fontFamily: "monospace",
  fontSize: 12,
  wordBreak: "break-all",
  padding: "4px 6px",
  borderRadius: 4,
  background: "rgba(255,255,255,0.06)",
};

function CopyButton({ text, label }: { text: string; label: string }) {
  const [result, setResult] = useState("");
  return (
    <PanelSectionRow>
      <ButtonItem
        layout="below"
        description={result ? <span style={note}>{result}</span> : undefined}
        onClick={async () =>
          setResult((await copyText(text)) ? "Copied." : "Copy did not work in Game Mode. Type the text shown above.")
        }
      >
        {label}
      </ButtonItem>
    </PanelSectionRow>
  );
}

function CompatCard({ section }: { section: CompatSection }) {
  const { proton, launch } = section;
  return (
    <PanelSection title="Compatibility">
      <PanelSectionRow>
        <div style={note}>Recommend only. Nothing is applied. Set these yourself in Steam.</div>
      </PanelSectionRow>
      {proton && (
        <PanelSectionRow>
          <Field focusable bottomSeparator="none" label="Proton">
            <div style={note}>
              <div>{protonLine(proton)}</div>
              {!proton.matches && <div>Where: {proton.where}.</div>}
              {proton.install_note && <div>{proton.install_note}</div>}
              {proton.as_reported && <div>As reported: {proton.as_reported}</div>}
            </div>
          </Field>
        </PanelSectionRow>
      )}
      {launch && (
        <>
          <PanelSectionRow>
            <Field focusable bottomSeparator="none" label="Launch options from the report">
              <div style={note}>
                <div style={mono}>{launch.recommended}</div>
                <div style={{ marginTop: 4 }}>Where: {launch.where}.</div>
                {launch.current && (
                  <div style={{ marginTop: 4 }}>
                    Yours now: <span style={mono}>{launch.current}</span>
                  </div>
                )}
                {launch.same_as_current && <div>You already use these.</div>}
              </div>
            </Field>
          </PanelSectionRow>
          {launch.flags.length > 0 && (
            <PanelSectionRow>
              <div style={warn}>
                {launch.flags.map((f, i) => (
                  <div key={i}>{f}</div>
                ))}
              </div>
            </PanelSectionRow>
          )}
          {!launch.same_as_current && <CopyButton text={launch.recommended} label="Copy launch options" />}
          {launch.merged && (
            <>
              <PanelSectionRow>
                <Field focusable bottomSeparator="none" label="Combined with yours">
                  <div style={note}>
                    <div style={mono}>{launch.merged}</div>
                    {launch.merge_notes.map((n, i) => (
                      <div key={i} style={{ marginTop: 2 }}>
                        {n}
                      </div>
                    ))}
                  </div>
                </Field>
              </PanelSectionRow>
              <CopyButton text={launch.merged} label="Copy combined launch options" />
            </>
          )}
        </>
      )}
    </PanelSection>
  );
}

function AiCard({ view, apply }: { view: View; apply: (v: View | undefined) => void }) {
  const [models, setModels] = useState<{ id: string; label: string }[]>([]);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");
  const providerId = view.settings.ai_provider;
  const provider = view.ai.providers.find((p) => p.id === providerId);
  const result = view.ai.result;
  const save = async (values: Partial<AdvisorSettings>) => apply((await saveSettings(values)).view);

  const load = async () => {
    setMessage("");
    const res = await listModels(providerId);
    if (res.ok) {
      setModels(res.models ?? []);
      if (!res.models?.length) setMessage("No text models found for this key.");
    } else setMessage(res.error?.message ?? "Could not load models.");
  };

  const modelOptions = models.length
    ? models.map((m) => ({ data: m.id, label: m.label }))
    : view.settings.ai_model
      ? [{ data: view.settings.ai_model, label: view.settings.ai_model }]
      : [];

  return (
    <PanelSection title="AI recommendation (optional)">
      <PanelSectionRow>
        <DropdownItem
          label="Provider"
          rgOptions={[{ data: "", label: "Off" }, ...view.ai.providers.map((p) => ({ data: p.id, label: p.name }))]}
          selectedOption={providerId}
          onChange={(o) => {
            setModels([]);
            save({ ai_provider: o.data as AdvisorSettings["ai_provider"] });
          }}
        />
      </PanelSectionRow>
      {provider && !provider.key.set && (
        <PanelSectionRow>
          <div style={note}>Add your {provider.name} API key in settings below first.</div>
        </PanelSectionRow>
      )}
      {provider && provider.key.set && (
        <>
          <PanelSectionRow>
            <ButtonItem layout="below" onClick={load}>
              Load model list
            </ButtonItem>
          </PanelSectionRow>
          {modelOptions.length > 0 && (
            <PanelSectionRow>
              <DropdownItem
                label="Model"
                rgOptions={modelOptions}
                selectedOption={view.settings.ai_model || null}
                strDefaultLabel="Choose a model"
                onChange={(o) => save({ ai_model: o.data as string })}
              />
            </PanelSectionRow>
          )}
          <PanelSectionRow>
            <ButtonItem
              layout="below"
              disabled={busy || !view.settings.ai_model || !view.game}
              description={<span style={note}>{aiPrivacyLine(provider.name)}</span>}
              onClick={async () => {
                setBusy(true);
                try {
                  apply((await generateAi()).view);
                } finally {
                  setBusy(false);
                }
              }}
            >
              {busy ? "Generating..." : "Generate AI recommendation"}
            </ButtonItem>
          </PanelSectionRow>
          <PanelSectionRow>
            <div style={note}>{capLine(view.ai.used_today, view.settings.ai_daily_cap)}</div>
          </PanelSectionRow>
        </>
      )}
      {message && (
        <PanelSectionRow>
          <div style={note}>{message}</div>
        </PanelSectionRow>
      )}
      {result && (
        <PanelSectionRow>
          <div style={result.error ? warn : { ...warn, background: "#2a3a4f" }}>{aiStatus(result)}</div>
        </PanelSectionRow>
      )}
      {result?.rec &&
        groups(result.rec).map((g) => (
          <PanelSectionRow key={g.title}>
            <Field focusable bottomSeparator="none" label={g.title}>
              <div style={note}>
                {g.lines.map((line, i) => (
                  <div key={i}>{line}</div>
                ))}
              </div>
            </Field>
          </PanelSectionRow>
        ))}
      {result?.rec && (result.rec.flags.length > 0 || result.discarded.length > 0) && (
        <PanelSectionRow>
          <div style={warn}>
            {result.rec.flags.map((f, i) => (
              <div key={`f${i}`}>{f}</div>
            ))}
            {result.discarded.length > 0 && <div>Discarded from the reply:</div>}
            {result.discarded.map((d, i) => (
              <div key={`d${i}`}>{d}</div>
            ))}
          </div>
        </PanelSectionRow>
      )}
      {result?.rec?.notes && (
        <PanelSectionRow>
          <Field focusable bottomSeparator="none" label="Model notes">
            <div style={note}>{result.rec.notes}</div>
          </Field>
        </PanelSectionRow>
      )}
      {result?.rec?.compat_section && <CompatCard section={result.rec.compat_section} />}
    </PanelSection>
  );
}

function KeyRow({ provider, apply }: { provider: AiProviderView; apply: (v: View | undefined) => void }) {
  const [value, setValue] = useState("");
  const name = SECRET_FOR[provider.id];
  return (
    <>
      <PanelSectionRow>
        <TextField
          label={`${provider.name} API key`}
          description={
            <span style={note}>
              {provider.key.set ? `Stored (${provider.key.masked}).` : "Not set."} Use a dedicated key with a spending limit.
            </span>
          }
          bIsPassword
          value={value}
          onChange={(e) => setValue(e.target.value)}
        />
      </PanelSectionRow>
      <PanelSectionRow>
        <ButtonItem
          layout="below"
          disabled={!value}
          onClick={async () => {
            apply((await setSecret(name, value)).view);
            setValue("");
          }}
        >
          Save {provider.name} key
        </ButtonItem>
      </PanelSectionRow>
      {provider.key.set && (
        <PanelSectionRow>
          <ButtonItem layout="below" onClick={async () => apply((await clearSecret(name)).view)}>
            Clear {provider.name} key
          </ButtonItem>
        </PanelSectionRow>
      )}
    </>
  );
}

function AiSettings({ view, apply }: { view: View; apply: (v: View | undefined) => void }) {
  const [message, setMessage] = useState("");
  const importKeys = async () => {
    const res = await importFromFile();
    if (!res.ok) {
      setMessage(res.message ?? "Import failed.");
      return;
    }
    apply(res.view);
    setMessage(`Imported ${res.imported?.join(", ")}.`);
    showModal(
      <ConfirmModal
        strTitle="Delete the import file?"
        strDescription={`The file at ${res.path} still holds your keys in plain text. Delete it now.`}
        strOKButtonText="Delete file"
        strCancelButtonText="Keep it"
        onOK={async () => setMessage((await deleteImportFile()).message ?? "")}
      />,
    );
  };
  return (
    <>
      {view.ai.providers.map((p) => (
        <KeyRow key={p.id} provider={p} apply={apply} />
      ))}
      <PanelSectionRow>
        <ButtonItem layout="below" onClick={importKeys} description={<span style={note}>Reads {view.import_path}</span>}>
          Import keys from file
        </ButtonItem>
      </PanelSectionRow>
      <PanelSectionRow>
        <DropdownItem
          label="Daily AI request limit"
          rgOptions={[0, 5, 10, 20, 50].map((n) => ({ data: n, label: n === 0 ? "No limit" : `${n} a day` }))}
          selectedOption={view.settings.ai_daily_cap}
          onChange={async (o) => apply((await saveSettings({ ai_daily_cap: o.data as number })).view)}
        />
      </PanelSectionRow>
      {message && (
        <PanelSectionRow>
          <div style={note}>{message}</div>
        </PanelSectionRow>
      )}
    </>
  );
}

function PcgwCard({ view }: { view: View }) {
  const state = view.pcgw;
  if (!state.enabled) return null;
  return (
    <PanelSection title="PCGamingWiki">
      {state.error && (
        <PanelSectionRow>
          <div style={warn}>{state.error.message}</div>
        </PanelSectionRow>
      )}
      {!state.data && !state.error && (
        <PanelSectionRow>
          <div style={note}>No PCGamingWiki page found for this game.</div>
        </PanelSectionRow>
      )}
      {state.data &&
        pcgwLines(state.data).map((g) => (
          <PanelSectionRow key={g.title}>
            <Field focusable bottomSeparator="none" label={g.title}>
              <div style={{ ...note, wordBreak: "break-word" }}>
                {g.lines.map((line, i) => (
                  <div key={i}>{line}</div>
                ))}
              </div>
            </Field>
          </PanelSectionRow>
        ))}
      {state.data?.files.length ? (
        <PanelSectionRow>
          <div style={note}>Windows paths sit inside the game's Proton prefix, under steamapps/compatdata/APPID/pfx/drive_c.</div>
        </PanelSectionRow>
      ) : null}
      {state.data && (
        <PanelSectionRow>
          <ButtonItem layout="below" onClick={() => open(state.data!.url)}>
            Open the PCGamingWiki page
          </ButtonItem>
        </PanelSectionRow>
      )}
      <PanelSectionRow>
        <div style={note}>
          {state.data?.attribution ?? "From PCGamingWiki, CC BY-NC-SA."}
          {state.cached ? " Cached." : ""}
        </div>
      </PanelSectionRow>
    </PanelSection>
  );
}

function SourceSettings({ view, apply }: { view: View; apply: (v: View | undefined) => void }) {
  const [username, setUsername] = useState(view.settings.pcgw_username);
  const [password, setPassword] = useState("");
  const save = async (values: Partial<AdvisorSettings>) => apply((await saveSettings(values)).view);
  return (
    <>
      <PanelSectionRow>
        <ToggleField
          label="ProtonDB reports"
          description={
            <span style={note}>
              Downloads a 2 MB index of handheld reports from GitHub once, then monthly. ODbL data from ProtonDB.
            </span>
          }
          checked={view.settings.source_protondb}
          onChange={(v) => save({ source_protondb: v })}
        />
      </PanelSectionRow>
      <PanelSectionRow>
        <ToggleField
          label="PCGamingWiki"
          description={
            <span style={note}>
              Needs your own bot password from PCGamingWiki, Special:BotPasswords, with the Cargo query grant. Sends the
              app ID to pcgamingwiki.com.
            </span>
          }
          checked={view.settings.source_pcgw}
          onChange={(v) => save({ source_pcgw: v })}
        />
      </PanelSectionRow>
      {view.settings.source_pcgw && (
        <>
          <PanelSectionRow>
            <TextField
              label="PCGamingWiki bot user name"
              description={<span style={note}>As shown on Special:BotPasswords, for example YourName@advisor.</span>}
              value={username}
              onChange={(e) => setUsername(e.target.value)}
              onBlur={() => username !== view.settings.pcgw_username && save({ pcgw_username: username })}
            />
          </PanelSectionRow>
          <PanelSectionRow>
            <TextField
              label="PCGamingWiki bot password"
              description={<span style={note}>{view.pcgw.has_password ? "Stored." : "Not set."}</span>}
              bIsPassword
              value={password}
              onChange={(e) => setPassword(e.target.value)}
            />
          </PanelSectionRow>
          <PanelSectionRow>
            <ButtonItem
              layout="below"
              disabled={!password}
              onClick={async () => {
                apply((await setPcgwPassword(password)).view);
                setPassword("");
              }}
            >
              Save bot password
            </ButtonItem>
          </PanelSectionRow>
        </>
      )}
    </>
  );
}

function SettingsSection({ view, apply }: { view: View; apply: (v: View | undefined) => void }) {
  const [message, setMessage] = useState("");
  const save = async (values: Partial<AdvisorSettings>) => {
    const res = await saveSettings(values);
    if (res.ok) apply(res.view);
    else setMessage(res.message ?? "Could not save.");
  };
  return (
    <>
      <PanelSectionRow>
        <DropdownItem
          label="Device"
          rgOptions={[{ data: "", label: "Detect automatically" }, ...view.devices.map((d) => ({ data: d.id, label: d.name }))]}
          selectedOption={view.settings.device_override}
          onChange={(o) => save({ device_override: o.data as string })}
        />
      </PanelSectionRow>
      {view.stack.categories.map((cat) => (
        <PanelSectionRow key={cat}>
          <DropdownItem
            label={CATEGORY_LABELS[cat] ?? cat}
            description={<span style={note}>Using {optionLabel(view, view.stack.selected[cat] ?? "none")}</span>}
            rgOptions={["auto", "none", ...(view.stack.options[cat] ?? [])].map((id) => ({ data: id, label: optionLabel(view, id) }))}
            selectedOption={view.settings.stack_overrides[cat] ?? "auto"}
            onChange={(o) => save({ stack_overrides: { ...view.settings.stack_overrides, [cat]: o.data as string } })}
          />
        </PanelSectionRow>
      ))}
      <PanelSectionRow>
        <ToggleField
          label="Deck Verified reports"
          description={<span style={note}>Sends the game's Steam app ID to deckverified.games.</span>}
          checked={view.settings.source_deckverified}
          onChange={(v) => save({ source_deckverified: v })}
        />
      </PanelSectionRow>
      <PanelSectionRow>
        <ButtonItem layout="below" onClick={async () => apply((await redetect()).view)}>
          Detect device and tools again
        </ButtonItem>
      </PanelSectionRow>
      <PanelSectionRow>
        <ButtonItem
          layout="below"
          onClick={async () => {
            const res = await clearCache();
            setMessage(`Cleared ${res.removed} cached ${res.removed === 1 ? "report" : "reports"}.`);
          }}
        >
          Clear cache
        </ButtonItem>
      </PanelSectionRow>
      <SourceSettings view={view} apply={apply} />
      <AiSettings view={view} apply={apply} />
      <PanelSectionRow>
        <ToggleField label="Check for updates daily" checked={view.settings.update_check} onChange={(v) => save({ update_check: v })} />
      </PanelSectionRow>
      <PanelSectionRow>
        <ToggleField
          label="Remove settings on uninstall"
          description="Updating by installing from the URL again counts as an uninstall. Leave this off to keep your keys."
          checked={view.settings.remove_data_on_uninstall}
          onChange={(v) => save({ remove_data_on_uninstall: v })}
        />
      </PanelSectionRow>
      {message && (
        <PanelSectionRow>
          <div style={note}>{message}</div>
        </PanelSectionRow>
      )}
      <PanelSectionRow>
        <Field label="Detected hardware" focusable bottomSeparator="none">
          <div style={{ ...note, fontFamily: "monospace", wordBreak: "break-all" }}>
            {Object.entries(view.device.facts)
              .filter(([, v]) => v)
              .map(([k, v]) => (
                <div key={k}>
                  {k}: {v}
                </div>
              ))}
          </div>
        </Field>
      </PanelSectionRow>
      <PanelSectionRow>
        <Field label="Version" bottomSeparator="none" focusable={false}>
          <span style={note}>{view.version}</span>
        </Field>
      </PanelSectionRow>
    </>
  );
}

function Content() {
  const [view, setView] = useState<View | null>(null);
  const [index, setIndex] = useState(0);
  const [loading, setLoading] = useState(false);
  const [showSettings, setShowSettings] = useState(false);
  const [recent, setRecent] = useState<GameRef[]>([]);

  const apply = (v: View | undefined) => {
    if (v) {
      setView(v);
      setIndex((i) => Math.min(i, Math.max(0, v.recommendations.length - 1)));
    }
  };

  const pick = async (game: GameRef) => {
    setLoading(true);
    try {
      const res = await sendGame(game);
      apply(res.view);
      setIndex(0);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    (async () => {
      const current = await getView();
      setView(current);
      const playing = runningGame() ?? lastSeen;
      const known = current.game?.appid ?? current.game?.shortcut_appid;
      if (playing && follower.shouldFollow(playing.appid) && playing.appid !== known) {
        await pick(playing);
      } else if (known && current.game) {
        // Launch options may have changed since the game was picked. Read them again.
        const fresh = await currentCompat(known, current.game.shortcut);
        apply((await setCurrentCompat(fresh.launchOptions, fresh.compatTool)).view);
      }
      setRecent(recentGames());
    })();
  }, []);

  useBackendEvent<View["update"]>("update", (u) => setView((v) => (v ? { ...v, update: u } : v)));

  if (!view) {
    return (
      <PanelSection>
        <PanelSectionRow>
          <div style={note}>Loading...</div>
        </PanelSectionRow>
      </PanelSection>
    );
  }

  return (
    <>
      <PanelSection>
        <PanelSectionRow>
          <Field label={gameTitle(view.game)} focusable bottomSeparator="none">
            <div style={note}>
              <div>{deviceLine(view)}</div>
              <div>{stackSummary(view)}</div>
              {view.device.generic && <div>No registry entry for this device. A device PR is welcome.</div>}
            </div>
          </Field>
        </PanelSectionRow>
        {view.conflicts.map((c) => (
          <PanelSectionRow key={c.kind}>
            <div style={warn}>{c.text}</div>
          </PanelSectionRow>
        ))}
        {view.source.error && (
          <PanelSectionRow>
            <div style={warn}>
              {view.source.cached ? "Showing cached reports. " : "No reports. "}
              {view.source.error.message}
            </div>
          </PanelSectionRow>
        )}
        <UpdateBadge update={view.update} />
        {recent.length > 0 && (
          <PanelSectionRow>
            <DropdownItem
              label={view.game ? "Pick another game" : "Pick a recent game"}
              rgOptions={recent.map((g) => ({ data: g.appid, label: g.name }))}
              selectedOption={view.game?.appid ?? view.game?.shortcut_appid ?? null}
              strDefaultLabel="Choose"
              onChange={(o) => {
                const game = recent.find((g) => g.appid === o.data);
                if (game) pick(game);
              }}
            />
          </PanelSectionRow>
        )}
        {view.game && (
          <PanelSectionRow>
            <ButtonItem layout="below" disabled={loading} onClick={async () => apply((await refresh()).view)}>
              {loading ? "Loading reports..." : "Refresh reports"}
            </ButtonItem>
          </PanelSectionRow>
        )}
      </PanelSection>

      {view.game && protondbLine(view.protondb) && (
        <PanelSection>
          <PanelSectionRow>
            <div style={view.protondb.error ? warn : note}>
              {protondbLine(view.protondb)} {view.protondb.summary?.attribution ?? ""}
            </div>
          </PanelSectionRow>
        </PanelSection>
      )}

      <RecommendationCard view={view} index={index} setIndex={setIndex} apply={apply} />

      {view.recommendations[index]?.compat_section && (
        <CompatCard section={view.recommendations[index].compat_section as CompatSection} />
      )}

      {view.game && <PcgwCard view={view} />}

      {view.game && <AiCard view={view} apply={apply} />}

      {view.game && (
        <PanelSection title="More about this game">
          {linkOuts(view.game).map((l) => (
            <PanelSectionRow key={l.label}>
              <ButtonItem layout="below" onClick={() => open(l.url)}>
                {l.label}
              </ButtonItem>
            </PanelSectionRow>
          ))}
        </PanelSection>
      )}

      <PanelSection title="Settings">
        <PanelSectionRow>
          <ButtonItem layout="below" onClick={() => setShowSettings(!showSettings)}>
            {showSettings ? "Hide settings" : "Show settings"}
          </ButtonItem>
        </PanelSectionRow>
        {showSettings && <SettingsSection view={view} apply={apply} />}
        <PanelSectionRow>
          <div style={note}>Recommends only. Never changes Steam, other plugins or game files. Reports from Deck Verified (GPL-3.0).</div>
        </PanelSectionRow>
      </PanelSection>
    </>
  );
}

export default definePlugin(() => {
  const stopWatching = watchGames(
    (game) => {
      lastSeen = game;
      follower.started(game.appid);
      sendGame(game);
    },
    () => {
      lastSeen = null;
      follower.stopped();
    },
  );

  return {
    name: "Tuning Advisor",
    titleView: <div className={staticClasses.Title}>Tuning Advisor</div>,
    content: <Content />,
    icon: <FaSlidersH />,
    onDismount() {
      stopWatching();
    },
  };
});
