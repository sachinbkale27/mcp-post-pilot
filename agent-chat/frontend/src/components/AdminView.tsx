import { useCallback, useEffect, useState, type FormEvent } from "react";
import { BarChart3, CircleAlert, LoaderCircle, LogOut, RotateCcw } from "lucide-react";
import { API_URL } from "../api";

/** The usage analytics, for a signed-in admin only (as Image Label's admin page): sign-in, then the numbers. */

const TOKEN_KEY = "adminToken";
const PERIODS = [1, 7, 30, 90];

interface Row { key: string; count: number }
interface Feature { key: string; title: string; count: number; visitors: number; errors: number; error_rate: number; p50_ms: number | null; p95_ms: number | null }
interface Usage {
  totals: { visitors: number; sessions: number; views: number; runs: number; errors: number };
  daily: { day: string; visitors: number; views: number; runs: number }[];
  views: Row[]; features: Feature[]; agents: Row[]; tools: Row[]; downloads: Row[];
  referrers: Row[]; campaigns: Row[]; countries: Row[]; devices: Row[]; browsers: Row[]; os: Row[];
}

const VIEW_NAMES: Record<string, string> = { chat: "Chat", label: "Annotate Images", trials: "Clinical Trials", medicines: "Medicines", security: "App Security" };
const DOWNLOAD_NAMES: Record<string, string> = {
  coco: "COCO JSON", yolo: "YOLO labels", yolo_classes: "YOLO classes", qupath: "QuPath GeoJSON", figure: "Annotated image (PNG)", image: "Image",
};
const COUNTRY = typeof Intl.DisplayNames === "function" ? new Intl.DisplayNames(undefined, { type: "region" }) : undefined;
const countryName = (code: string) => { try { return COUNTRY?.of(code) ?? code; } catch { return code; } };
const seconds = (ms: number | null) => (ms === null ? "–" : ms < 1000 ? `${ms} ms` : `${(ms / 1000).toFixed(ms < 10_000 ? 1 : 0)} s`);
const percent = (x: number) => `${(x * 100).toFixed(x > 0 && x < 0.1 ? 1 : 0)}%`;

function readToken(): string | null {
  try { return sessionStorage.getItem(TOKEN_KEY); } catch { return null; }
}

function writeToken(token: string | null) {
  try { token ? sessionStorage.setItem(TOKEN_KEY, token) : sessionStorage.removeItem(TOKEN_KEY); } catch { /* private mode */ }
}

export function AdminView({ active }: { active: boolean }) {
  const [token, setToken] = useState<string | null>(readToken);
  const signOut = useCallback(() => { writeToken(null); setToken(null); }, []); // stable: UsagePanel reloads on change

  return (
    <div className="label-view">
      <header className="label-intro">
        <h2><BarChart3 size={22} aria-hidden /> Usage</h2>
        <p>
          Who uses this site and which agents and features they use. Visitors are counted per day with an id that changes
          daily and can't be traced to an address; bots, browsers that ask not to be tracked, and your own browsers
          (<span className="mono">?internal=1</span>) are left out.
        </p>
        {token && <button className="link-btn" onClick={signOut}><LogOut size={14} aria-hidden /> Sign out</button>}
      </header>
      {token ? (
        active && <UsagePanel token={token} onExpired={signOut} />
      ) : (
        <SignIn onSignedIn={(t) => { writeToken(t); setToken(t); }} />
      )}
    </div>
  );
}

function SignIn({ onSignedIn }: { onSignedIn: (token: string) => void }) {
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string>();
  const [busy, setBusy] = useState(false);

  async function submit(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(undefined);
    try {
      const res = await fetch(`${API_URL}/admin/login`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ username, password }),
      });
      const body = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(typeof body.detail === "string" ? body.detail : "Invalid username or password");
      if (!body.admin) throw new Error("This account isn't an admin.");
      onSignedIn(body.token);
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
      setPassword("");
    }
  }

  return (
    <form className="label-panel admin-signin" onSubmit={submit}>
      <h3>Admin sign-in</h3>
      {error && <p className="label-alert" role="alert"><CircleAlert size={16} aria-hidden /> {error}</p>}
      <label className="label-field">
        <span>Username</span>
        <input className="label-input" value={username} onChange={(e) => setUsername(e.target.value)} autoComplete="username" required />
      </label>
      <label className="label-field">
        <span>Password</span>
        <input className="label-input" type="password" value={password} onChange={(e) => setPassword(e.target.value)}
          autoComplete="current-password" required />
      </label>
      <button className="label-run" type="submit" disabled={busy || !username || !password}>
        {busy ? <><LoaderCircle size={16} className="spin" aria-hidden /> Signing in…</> : "Sign in"}
      </button>
    </form>
  );
}

function UsagePanel({ token, onExpired }: { token: string; onExpired: () => void }) {
  const [days, setDays] = useState(7);
  const [includeMine, setIncludeMine] = useState(false);
  const [usage, setUsage] = useState<Usage>();
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string>();

  const load = useCallback(async () => {
    setLoading(true);
    setError(undefined);
    try {
      const res = await fetch(`${API_URL}/admin/usage?days=${days}${includeMine ? "&internal=true" : ""}`, {
        headers: { "X-Admin-Session": token },
      });
      if (res.status === 401) return onExpired(); // expired (12 hours) or signed with an older key
      const body = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(typeof body.detail === "string" ? body.detail : `Could not load usage (${res.status})`);
      setUsage(body);
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setLoading(false);
    }
  }, [token, days, includeMine, onExpired]);

  useEffect(() => { load(); }, [load]);

  return (
    <div className="admin-usage">
      <div className="admin-filters">
        <div className="segmented admin-periods" role="radiogroup" aria-label="Period">
          {PERIODS.map((d) => (
            <button key={d} role="radio" aria-checked={days === d} className={days === d ? "active" : undefined} onClick={() => setDays(d)}>
              {d === 1 ? "Today" : `${d} days`}
            </button>
          ))}
        </div>
        <label className="admin-toggle">
          <input type="checkbox" checked={includeMine} onChange={(e) => setIncludeMine(e.target.checked)} /> Include my visits
        </label>
        <button className="icon-btn" onClick={load} disabled={loading} aria-label="Refresh" title="Refresh">
          {loading ? <LoaderCircle size={16} className="spin" aria-hidden /> : <RotateCcw size={16} aria-hidden />}
        </button>
      </div>

      {error && <p className="label-alert" role="alert"><CircleAlert size={16} aria-hidden /> {error}</p>}

      {usage && (
        <>
          <div className="admin-tiles">
            <Tile label="Visitors" value={usage.totals.visitors} hint="Counted per day: someone back on 3 days counts 3 times" />
            <Tile label="Sessions" value={usage.totals.sessions} hint="Browser tabs" />
            <Tile label="Views" value={usage.totals.views} />
            <Tile label="Agent runs" value={usage.totals.runs} hint="Chat turns, annotations, searches and other actions" />
            <Tile label="Failed runs" value={usage.totals.errors} />
          </div>

          {usage.daily.length > 1 && <DailyChart daily={usage.daily} />}

          <section className="label-panel admin-section">
            <h3>Features</h3>
            {usage.features.length ? (
              <div className="admin-table-wrap">
                <table className="admin-table">
                  <thead><tr><th>Feature</th><th>Uses</th><th>Visitors</th><th>Failed</th><th>Typical time</th><th>Slowest 5%</th></tr></thead>
                  <tbody>
                    {usage.features.map((f) => (
                      <tr key={f.key}>
                        <td>{f.title}</td><td>{f.count}</td><td>{f.visitors}</td>
                        <td>{f.errors ? `${f.errors} (${percent(f.error_rate)})` : "0"}</td>
                        <td>{seconds(f.p50_ms)}</td><td>{seconds(f.p95_ms)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            ) : <p className="admin-empty">No agent runs in this period.</p>}
          </section>

          <div className="admin-grid">
            <RankList title="Views" rows={usage.views} name={(k) => VIEW_NAMES[k] ?? k} />
            <RankList title="Agents" rows={usage.agents} hint="Chat turns and runs each agent took part in" />
            <RankList title="Tools" rows={usage.tools} mono />
            <RankList title="Downloads" rows={usage.downloads} name={(k) => DOWNLOAD_NAMES[k] ?? k} />
            <RankList title="Referrers" rows={usage.referrers} empty="Direct visits only" />
            <RankList title="Campaigns (utm_source)" rows={usage.campaigns} empty="None" />
            <RankList title="Countries" rows={usage.countries} name={countryName} hint="Visitors per day" />
            <RankList title="Devices" rows={usage.devices} name={(k) => k[0].toUpperCase() + k.slice(1)} />
            <RankList title="Browsers" rows={usage.browsers} />
            <RankList title="Operating systems" rows={usage.os} />
          </div>
        </>
      )}
    </div>
  );
}

function Tile({ label, value, hint }: { label: string; value: number; hint?: string }) {
  return (
    <div className="admin-tile" title={hint}>
      <span>{label}</span>
      <strong>{value.toLocaleString()}</strong>
    </div>
  );
}

/** Visitors per day: one series, so no legend; the hover tooltip and the table carry the exact numbers. */
function DailyChart({ daily }: { daily: Usage["daily"] }) {
  const [hover, setHover] = useState<number>();
  const [asTable, setAsTable] = useState(false);
  const max = Math.max(1, ...daily.map((d) => d.visitors));
  const label = (day: string) => new Date(`${day}T00:00:00Z`).toLocaleDateString(undefined, { month: "short", day: "numeric", timeZone: "UTC" });
  const shown = hover !== undefined ? daily[hover] : undefined;
  const tickEvery = Math.ceil(daily.length / 7);

  return (
    <section className="label-panel admin-section">
      <div className="admin-section-head">
        <h3>Visitors per day</h3>
        <button className="link-btn" onClick={() => setAsTable((t) => !t)}>{asTable ? "Show chart" : "Show table"}</button>
      </div>
      {asTable ? (
        <div className="admin-table-wrap">
          <table className="admin-table">
            <thead><tr><th>Day (UTC)</th><th>Visitors</th><th>Views</th><th>Agent runs</th></tr></thead>
            <tbody>{[...daily].reverse().map((d) => <tr key={d.day}><td>{label(d.day)}</td><td>{d.visitors}</td><td>{d.views}</td><td>{d.runs}</td></tr>)}</tbody>
          </table>
        </div>
      ) : (
        <div className="admin-chart" onMouseLeave={() => setHover(undefined)}>
          <div className="admin-chart-y" aria-hidden><span>{max}</span><span>0</span></div>
          <div className="admin-chart-plot" role="img" aria-label={`Visitors per day, at most ${max}`}>
            {daily.map((d, i) => (
              <div key={d.day} className={`admin-bar-slot${hover === i ? " hover" : ""}`} onMouseEnter={() => setHover(i)}
                onFocus={() => setHover(i)} tabIndex={0} aria-label={`${label(d.day)}: ${d.visitors} visitors`}>
                <div className="admin-bar" style={{ height: `${(d.visitors / max) * 100}%` }} />
                {i % tickEvery === 0 && <span className="admin-bar-tick">{label(d.day)}</span>}
              </div>
            ))}
            {shown && hover !== undefined && (
              <div className="admin-tooltip" style={tooltipPosition((hover + 0.5) / daily.length)}>
                <strong>{label(shown.day)}</strong>
                <span>{shown.visitors} visitors · {shown.views} views · {shown.runs} runs</span>
              </div>
            )}
          </div>
        </div>
      )}
    </section>
  );
}

/** Centered over its bar, but kept inside the chart near either edge (no sideways scroll on a phone). */
function tooltipPosition(at: number) {
  const left = `${at * 100}%`;
  if (at < 0.3) return { left, transform: "translateX(-12px)" };
  if (at > 0.7) return { left, transform: "translateX(calc(-100% + 12px))" };
  return { left, transform: "translateX(-50%)" };
}

function RankList({ title, rows, name = (k) => k, hint, empty = "No data yet", mono }: {
  title: string; rows: Row[]; name?: (key: string) => string; hint?: string; empty?: string; mono?: boolean;
}) {
  const max = Math.max(1, ...rows.map((r) => r.count));
  return (
    <section className="label-panel admin-section" title={hint}>
      <h3>{title}</h3>
      {rows.length ? (
        <ol className="admin-rank">
          {rows.map((r) => (
            <li key={r.key}>
              <span className={mono ? "mono" : undefined}>{name(r.key)}</span>
              <span className="admin-rank-bar" style={{ width: `${(r.count / max) * 100}%` }} aria-hidden />
              <strong>{r.count}</strong>
            </li>
          ))}
        </ol>
      ) : <p className="admin-empty">{empty}</p>}
    </section>
  );
}
