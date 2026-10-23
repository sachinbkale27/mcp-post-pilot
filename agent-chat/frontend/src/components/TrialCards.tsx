import { CircleCheck, ExternalLink, FlaskConical, MapPin, ShieldQuestion } from "lucide-react";
import type { Trial } from "../api";

/** What each registry status means, shown as the badge's tooltip. */
const STATUS_HELP: Record<string, string> = {
  "Recruiting": "Currently enrolling participants.",
  "Not yet recruiting": "Approved and listed, but not enrolling yet.",
  "Enrolling by invitation": "Only people invited by the trial team can join.",
  "Active, not recruiting": "Running, but no longer enrolling.",
  "Completed": "Finished; results may or may not be posted.",
  "Suspended": "Paused; it may restart.",
  "Terminated": "Stopped early; the registry may say why.",
  "Withdrawn": "Stopped before enrolling anyone.",
};

const PHASE_HELP: Record<string, string> = {
  "Early phase 1": "Very small first-in-human study of how a drug behaves in the body.",
  "Phase 1": "Is it safe, and at what dose? Usually 20 to 80 people.",
  "Phase 2": "Does it work, and is the dose right? Usually 100 to 300 people.",
  "Phase 3": "Is it better than the current standard? Hundreds to thousands of people.",
  "Phase 4": "After approval: long-term safety and use in practice.",
  "Not applicable": "Not a drug trial (e.g. a device, procedure or behavioural study).",
};

const statusClass = (status: string) =>
  status === "Recruiting" ? "open" : status === "Not yet recruiting" || status === "Enrolling by invitation" ? "soon" : "closed";

/** The trials the Clinical Trials agent filed: registry facts, plus why each matched and what to confirm. */
export function TrialCards({ trials }: { trials: Trial[] }) {
  if (trials.length === 0) return null;
  return (
    <section className="trials" aria-label="Clinical trials">
      {trials.map((t) => {
        const site = t.nearest_site;
        return (
          <article key={t.nct_id} className="trial">
            <header className="trial-head">
              <span className={`trial-badge status-${statusClass(t.status)}`} title={STATUS_HELP[t.status]}>{t.status}</span>
              {t.phases.map((p) => (
                <span key={p} className="trial-badge" title={PHASE_HELP[p]}>{p}</span>
              ))}
              {t.has_results && <span className="trial-badge" title="The sponsor posted results in the registry">Results posted</span>}
              <a className="trial-id mono" href={t.url} target="_blank" rel="noreferrer">
                {t.nct_id} <ExternalLink size={12} aria-hidden />
              </a>
            </header>
            <h4 className="trial-title">{t.title}</h4>
            <p className="trial-facts">
              <FlaskConical size={13} aria-hidden />
              {[t.interventions.join(", "), t.sponsor && `${t.sponsor}${t.sponsor_type ? ` (${t.sponsor_type.toLowerCase()})` : ""}`,
                t.enrollment ? `${t.enrollment} participants` : "", `ages ${t.ages.toLowerCase()}`]
                .filter(Boolean)
                .join(" · ")}
            </p>
            {site ? (
              <p className="trial-facts">
                <MapPin size={13} aria-hidden />
                {site.facility}, {site.city}, {site.country}
                {site.distance_km !== undefined && ` · ${site.distance_km} km away`} · site {site.status.toLowerCase()}
                {t.site_count > 1 && ` · ${t.site_count} sites in all`}
              </p>
            ) : (
              <p className="trial-facts"><MapPin size={13} aria-hidden /> {t.site_count} site{t.site_count === 1 ? "" : "s"}</p>
            )}
            <div className="trial-why">
              <CircleCheck size={14} aria-hidden />
              <div>
                <strong>Why this matched</strong> {t.why_matched}
                {t.evidence && <q className="trial-evidence" title="Quoted from the trial's registry record">{t.evidence}</q>}
              </div>
            </div>
            {t.to_confirm.length > 0 && (
              <div className="trial-confirm">
                <ShieldQuestion size={14} aria-hidden />
                <div>
                  <strong>Check with the trial team</strong>
                  <ul>{t.to_confirm.map((c) => <li key={c}>{c}</li>)}</ul>
                </div>
              </div>
            )}
            {t.why_stopped && <p className="trial-stopped">Stopped: {t.why_stopped}</p>}
            <footer className="trial-source">
              Source: <a href={t.url} target="_blank" rel="noreferrer">ClinicalTrials.gov</a>
              {t.last_update && ` · registry updated ${t.last_update}`}
            </footer>
          </article>
        );
      })}
      <p className="trials-note">
        Only the trial team can confirm eligibility. This is not medical advice: discuss trials with your doctor.
      </p>
    </section>
  );
}
