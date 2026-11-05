import { useRef, useState } from "react";
import Markdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { CircleAlert, LoaderCircle, RotateCcw, ShieldCheck, Square } from "lucide-react";
import { streamSecurity } from "../api";
import { applyEvent } from "../lib/events";
import { AgentCard, type Step } from "./Messages";

type Goal = "plan" | "review" | "token";

const GOALS: [Goal, string, string][] = [
  ["plan", "Plan sign-in", "Login, token checks, roles, infrastructure and tests for your stack"],
  ["review", "Review my setup", "Check an identity provider's settings and a site's security headers"],
  ["token", "Check a token", "Decode a test JWT, flag risky claims and verify its signature"],
];

const PROVIDERS = ["Amazon Cognito", "Auth0", "Okta", "Microsoft Entra ID", "Google", "Keycloak", "Not chosen yet"];

export interface SecurityForm {
  goal: Goal;
  frontend: string;
  backend: string;
  provider: string;
  protect: string;
  issuer: string;
  audience: string;
  site: string;
  token: string; // sent to the agent, never shown in the question or the answer
}

const EMPTY: SecurityForm = { goal: "plan", frontend: "", backend: "", provider: "Amazon Cognito", protect: "", issuer: "", audience: "", site: "", token: "" };

const EXAMPLES: { title: string; form: Partial<SecurityForm> }[] = [
  {
    title: "React + FastAPI on Lambda",
    form: { goal: "plan", frontend: "React single-page app", backend: "FastAPI on AWS Lambda behind API Gateway", provider: "Amazon Cognito", protect: "Only signed-in users can call /api/*; only admins can delete posts" },
  },
  {
    title: "Next.js with Auth0",
    form: { goal: "plan", frontend: "Next.js (App Router)", backend: "Next.js route handlers and a Node/Express API", provider: "Auth0", protect: "Paid users can use /api/reports; admins manage users" },
  },
  { title: "Check Google's provider", form: { goal: "review", provider: "Google", issuer: "https://accounts.google.com" } },
];

const sentence = (text: string) => text.trim().replace(/([^.?!])$/, "$1.");

/** The request in plain words: what the agent is asked (the token goes separately). */
export function buildRequest(f: SecurityForm): string {
  const app = [f.frontend.trim() && `${f.frontend.trim()} front end`, f.backend.trim() && `${f.backend.trim()} API`].filter(Boolean).join(" and ");
  const provider = f.provider === "Not chosen yet" ? "" : f.provider;
  const parts: string[] = [];
  if (f.goal === "plan") {
    parts.push(`Plan ${provider ? `${provider} ` : ""}sign-in for my app${app ? ` (${app})` : ""}.`);
    if (!provider) parts.push("I haven't chosen an identity provider yet: recommend one.");
    if (f.protect.trim()) parts.push(`What must be protected: ${sentence(f.protect)}`);
  } else if (f.goal === "review") {
    parts.push(`Review the sign-in security of my app${app ? ` (${app})` : ""}${provider ? `, which uses ${provider}` : ""}.`);
    if (f.protect.trim()) parts.push(`What must be protected: ${sentence(f.protect)}`);
  } else {
    parts.push("Inspect my test token: flag risky claims and settings.");
  }
  if (f.issuer.trim()) parts.push(`${f.goal === "token" ? "Verify it against" : "Check the identity provider at"} ${f.issuer.trim()}.`);
  if (f.audience.trim()) parts.push(`The API's expected audience (or client id) is ${f.audience.trim()}.`);
  if (f.site.trim()) parts.push(`Check the security headers and cookies of ${f.site.trim()}.`);
  if (f.token.trim() && f.goal !== "token") parts.push("Also inspect the test token I attached.");
  return parts.join(" ");
}

function ready(f: SecurityForm): boolean {
  if (f.goal === "plan") return !!(f.frontend.trim() || f.backend.trim()) && f.protect.trim().length >= 5;
  if (f.goal === "review") return !!(f.issuer.trim() || f.site.trim() || f.token.trim());
  return f.token.trim().split(".").length === 3;
}

interface Run {
  steps: Step[];
  report?: string;
  error?: string;
  pending: boolean;
}

interface Props {
  available: boolean;
  unavailableReason?: string;
  busy: boolean;
  onBusyChange: (busy: boolean) => void;
}

/** Plan or review an app's sign-in security with a short form, and watch the Auth Security agent work. */
export function SecurityView({ available, unavailableReason, busy, onBusyChange }: Props) {
  const [form, setForm] = useState<SecurityForm>(EMPTY);
  const [run, setRun] = useState<Run>();
  const abortRef = useRef<AbortController | null>(null);
  const set = (patch: Partial<SecurityForm>) => setForm((f) => ({ ...f, ...patch }));

  const question = buildRequest(form);
  const canRun = available && !busy && ready(form);

  async function start() {
    if (!canRun) return;
    const controller = new AbortController();
    abortRef.current = controller;
    onBusyChange(true);
    setRun({ steps: [], pending: true });
    const update = (fn: (r: Run) => Run) => setRun((r) => (r ? fn(r) : r));
    try {
      for await (const event of streamSecurity({ question, token: form.token.trim() }, controller.signal)) {
        if (event.type === "security_report") update((r) => ({ ...r, report: event.report }));
        else if (event.type === "error") update((r) => ({ ...r, error: event.message }));
        else update((r) => ({ ...r, steps: applyEvent(r.steps, event) }));
      }
    } catch (e) {
      const stopped = (e as Error).name === "AbortError";
      update((r) => ({ ...r, error: stopped ? "Stopped." : (e as Error).message }));
    } finally {
      abortRef.current = null;
      update((r) => ({ ...r, pending: false }));
      onBusyChange(false);
    }
  }

  return (
    <div className="label-view">
      <header className="label-intro">
        <h2><ShieldCheck size={22} aria-hidden /> App Security</h2>
        <p>
          The Auth Security agent plans OAuth 2.0 / OpenID Connect sign-in and JWT checks for your app, with code for your
          stack, identity provider and infrastructure setup, tests and a go-live checklist. It can also check an identity
          provider's settings, a test token and a site's security headers. It never changes your code or settings: you
          apply the plan.
        </p>
      </header>

      {!available && (
        <p className="label-alert">
          <CircleAlert size={16} aria-hidden /> {unavailableReason ?? "The Auth Security agent isn't available on this server."}
        </p>
      )}

      <div className="label-grid">
        <section className="label-panel" aria-labelledby="security-form-heading">
          <h3 id="security-form-heading">1. What do you need?</h3>
          <div className="segmented security-goals" role="radiogroup" aria-label="Goal">
            {GOALS.map(([goal, text, hint]) => (
              <button key={goal} role="radio" aria-checked={form.goal === goal} className={form.goal === goal ? "active" : undefined}
                onClick={() => set({ goal })} disabled={busy} title={hint}>
                {text}
              </button>
            ))}
          </div>
          <small className="label-hint">{GOALS.find(([g]) => g === form.goal)?.[2]}</small>

          {form.goal !== "token" && (
            <>
              <h3>2. Your app</h3>
              <label className="label-field">
                <span>Front end</span>
                <input className="label-input" value={form.frontend} placeholder="e.g. React single-page app, Next.js, iOS app"
                  onChange={(e) => set({ frontend: e.target.value })} disabled={busy} />
              </label>
              <label className="label-field">
                <span>Back end / API</span>
                <input className="label-input" value={form.backend} placeholder="e.g. FastAPI on AWS Lambda, Express on ECS, Django"
                  onChange={(e) => set({ backend: e.target.value })} disabled={busy} />
              </label>
              <div className="label-field">
                <span id="security-provider">Identity provider</span>
                <div className="trials-options" role="radiogroup" aria-labelledby="security-provider">
                  {PROVIDERS.map((p) => (
                    <button key={p} role="radio" aria-checked={form.provider === p} className={form.provider === p ? "chip active" : "chip"}
                      onClick={() => set({ provider: p })} disabled={busy}>
                      {p}
                    </button>
                  ))}
                </div>
              </div>
              <label className="label-field">
                <span>What must be protected {form.goal === "review" && <em>(optional)</em>}</span>
                <textarea className="label-input" rows={2} value={form.protect}
                  placeholder="e.g. Only signed-in users can call /api/*; only admins can delete posts"
                  onChange={(e) => set({ protect: e.target.value })} disabled={busy} />
              </label>
            </>
          )}

          <h3>{form.goal === "token" ? "2." : "3."} Check something <em>(optional{form.goal === "token" ? "" : ", for a review"})</em></h3>
          <label className="label-field">
            <span>Issuer URL</span>
            <input className="label-input" value={form.issuer} placeholder="e.g. https://cognito-idp.us-east-1.amazonaws.com/us-east-1_AbC123"
              onChange={(e) => set({ issuer: e.target.value })} disabled={busy} />
            <small className="label-hint">The identity provider's public settings and signing keys are read; nothing is changed.</small>
          </label>
          {form.goal === "token" && (
            <label className="label-field">
              <span>Expected audience or client id</span>
              <input className="label-input" value={form.audience} placeholder="e.g. my-api or the app client id"
                onChange={(e) => set({ audience: e.target.value })} disabled={busy} />
            </label>
          )}
          {form.goal !== "token" && (
            <label className="label-field">
              <span>Site URL</span>
              <input className="label-input" value={form.site} placeholder="e.g. https://app.example.com/login"
                onChange={(e) => set({ site: e.target.value })} disabled={busy} />
              <small className="label-hint">One ordinary request to check its HTTPS redirect, security headers and cookie flags.</small>
            </label>
          )}
          <label className="label-field">
            <span>Test token {form.goal !== "token" && <em>(optional)</em>}</span>
            <input className="label-input mono" type="password" autoComplete="off" spellCheck={false} value={form.token}
              placeholder="eyJhbGciOi…" onChange={(e) => set({ token: e.target.value })} disabled={busy} />
            <small className="label-hint">
              Test or expired tokens only, never a production one. It goes to the agent but is never shown back, and its
              signature and personal details aren't reported.
            </small>
          </label>

          <div className="trials-question" aria-live="polite">
            <span>The agent will be asked</span>
            <p>{question}{form.token.trim() && form.goal === "token" ? " (test token attached)" : ""}</p>
          </div>

          <div className="label-examples">
            {EXAMPLES.map((ex) => (
              <button key={ex.title} className="chip" disabled={busy} onClick={() => setForm({ ...EMPTY, ...ex.form })}>
                {ex.title}
              </button>
            ))}
          </div>

          <div className="label-actions">
            {busy ? (
              <button className="label-run" onClick={() => abortRef.current?.abort()}>
                <Square size={14} aria-hidden /> Stop
              </button>
            ) : (
              <button className="label-run" onClick={start} disabled={!canRun}>
                <ShieldCheck size={16} aria-hidden /> {form.goal === "plan" ? "Make the plan" : form.goal === "review" ? "Review" : "Check the token"}
              </button>
            )}
            {run && !busy && (
              <button className="link-btn" onClick={() => { setRun(undefined); setForm(EMPTY); }}>
                <RotateCcw size={13} aria-hidden /> Start over
              </button>
            )}
          </div>
        </section>

        <section className="label-panel label-output" aria-live="polite" aria-labelledby="security-result-heading">
          <h3 id="security-result-heading">Result</h3>
          {!run && (
            <ol className="medicine-steps">
              <li><strong>Checks what you gave it</strong>: the identity provider's settings, the token, the site's headers.</li>
              <li><strong>Plans the design</strong>: authorization code flow with PKCE, access tokens validated on every API call, roles.</li>
              <li><strong>Writes code, setup and tests</strong> for your stack, and a checklist before going live.</li>
            </ol>
          )}
          {run?.report && !run.pending && (
            <div className="answer"><Markdown remarkPlugins={[remarkGfm]}>{run.report}</Markdown></div>
          )}
          {run?.pending && (
            <p className="label-progress">
              <LoaderCircle size={15} className="spin" aria-hidden />
              {form.goal === "plan" ? "Writing the plan…" : "Checking…"}
              <span>{form.goal === "plan" ? "usually 1 to 2 minutes" : "usually under a minute"}</span>
            </p>
          )}
          {run?.error && <p className="label-alert"><CircleAlert size={16} aria-hidden /> {run.error}</p>}
          {run?.steps.map((step) => (step.type === "agent" ? <AgentCard key={step.id} step={step} showTrials={false} /> : null))}
          {run && !run.pending && (
            <p className="label-hint">AI-generated plan: review and test it before using it in production.</p>
          )}
        </section>
      </div>
    </div>
  );
}
