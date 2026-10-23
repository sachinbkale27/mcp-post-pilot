import { ChevronRight, CircleHelp, PlayCircle } from "lucide-react";

export type GuideStep = "condition" | "test" | "treatment" | "place" | "status" | "phase" | "patient" | "results" | "try";

interface Entry {
  id: GuideStep;
  title: string;
  what: string;
  where?: string;
  examples?: string[];
  tips?: string[];
}

/** What to enter in each part of the Clinical Trials form, in plain language. */
const GUIDE: Entry[] = [
  {
    id: "condition",
    title: "Disease or condition",
    what: "The name of the illness, as your doctor or your report writes it. This is the only thing you must enter.",
    where: "The diagnosis line of a discharge summary, pathology report, or doctor's letter.",
    examples: ["breast cancer", "non-small cell lung cancer", "type 2 diabetes", "rheumatoid arthritis", "Parkinson's disease"],
    tips: [
      "Use the medical name rather than a description: \"non-small cell lung cancer\", not \"tumour in my lung\".",
      "Leave out the stage here; you can add it under patient details.",
    ],
  },
  {
    id: "test",
    title: "Lab test result",
    what:
      "Mostly for cancers: a test on the tumour or blood that shows which type of the disease it is. Many trials only " +
      "take one type, so this can change the results a lot. Leave it blank if you don't have one.",
    where:
      "Pathology report (look for \"receptor status\" or \"IHC\") or a genetic or molecular test report (look for " +
      "\"mutation detected\", \"NGS\" or \"biomarker\").",
    examples: [
      "Breast cancer: HER2-positive, HER2-low, ER-positive, triple-negative",
      "Lung cancer: EGFR, ALK, KRAS G12C, PD-L1 high",
      "Bowel cancer: KRAS, MSI-high",
      "Melanoma: BRAF V600E",
    ],
    tips: ["Copy the words from the report exactly; spelling and capitals don't matter."],
  },
  {
    id: "treatment",
    title: "A treatment you're interested in",
    what: "Only show trials that test this treatment. Most people leave it blank to see everything.",
    examples: ["immunotherapy", "pembrolizumab", "CAR-T", "a vaccine", "physiotherapy"],
  },
  {
    id: "place",
    title: "City or country, and distance",
    what:
      "Trials run at hospitals (sites). Enter a city to find sites near it, or a country with \"Anywhere there\". " +
      "Leave it blank to search the whole world.",
    tips: [
      "Start with 300 km. If nothing turns up, try 1,000 km or the whole country.",
      "Big cities with cancer centres or university hospitals have the most trials.",
    ],
  },
  {
    id: "status",
    title: "Status",
    what: "Whether a trial is taking new participants.",
    tips: [
      "Recruiting now: enrolling today.",
      "Recruiting or opening soon (the default): also trials that are approved but haven't started enrolling.",
      "Any status: includes finished and stopped trials. Use it to learn what has been tested, not to join.",
    ],
  },
  {
    id: "phase",
    title: "Phase",
    what: "How far a new treatment has got in testing. Leave all off to see every phase.",
    tips: [
      "Phase 1: is it safe, and at what dose? Small groups; often for people who have tried other treatments.",
      "Phase 2: does it work? A few hundred people.",
      "Phase 3: is it better than the standard treatment? Hundreds to thousands of people.",
      "Phase 4: after approval, long-term safety.",
    ],
  },
  {
    id: "patient",
    title: "Patient details (optional)",
    what:
      "For one person's search. The agent checks each trial's rules against these details and leaves out trials " +
      "that clearly don't take them, saying why.",
    examples: ["60, female", "stage 4; spread to the liver", "progressed on osimertinib", "had chemotherapy in 2024", "also has kidney disease"],
    tips: [
      "Previous treatments matter most: many trials only take people who have, or haven't, had a certain treatment.",
      "Never enter names, ID numbers or other identifying details.",
    ],
  },
  {
    id: "results",
    title: "Reading the results",
    what: "Each trial appears as a card. Searches take about 20 to 60 seconds.",
    tips: [
      "Status and phase badges: hover over one for what it means.",
      "Why this matched: the agent's reason, with a quote from the trial's registry record.",
      "Check with the trial team: rules only the trial's doctors can confirm.",
      "The nearest site and a link to the full ClinicalTrials.gov entry, with contact details.",
      "Notes below the cards say which trials were left out and why.",
    ],
  },
  {
    id: "try",
    title: "Test it with a sample search",
    what: "Not sure where to start? Run one of the sample searches:",
    tips: [
      "Click \"Lung cancer after osimertinib\" under the form. It fills in every field, including patient details.",
      "Read the sentence under \"The agent will be asked\": it's your search in words. Change a field and watch it update.",
      "Press Find trials. Within a minute you should see a few trial cards, and a note under them if a trial was left out because its rules exclude this patient.",
    ],
  },
];

interface Props {
  active: GuideStep;
  onSelect: (step: GuideStep) => void;
}

/** A help panel that follows the form: the part being filled in is open. */
export function TrialsGuide({ active, onSelect }: Props) {
  return (
    <div className="trials-guide">
      <p className="trials-guide-intro">
        <CircleHelp size={15} aria-hidden /> How to use this page. Click a field in the form, or a topic below, to see
        what to enter.
      </p>
      {GUIDE.map((entry) => {
        const open = entry.id === active;
        return (
          <div key={entry.id} className={open ? "guide-entry open" : "guide-entry"}>
            <button className="guide-head" onClick={() => onSelect(entry.id)} aria-expanded={open}>
              {entry.id === "try" ? <PlayCircle size={15} aria-hidden /> : <ChevronRight size={15} className="chevron" aria-hidden />}
              {entry.title}
            </button>
            {open && (
              <div className="guide-body">
                <p>{entry.what}</p>
                {entry.where && <p><strong>Where to find it:</strong> {entry.where}</p>}
                {entry.examples && (
                  <p className="guide-examples">
                    <strong>Examples:</strong> {entry.examples.map((e) => <span key={e} className="chip">{e}</span>)}
                  </p>
                )}
                {entry.tips && <ul>{entry.tips.map((t) => <li key={t}>{t}</li>)}</ul>}
              </div>
            )}
          </div>
        );
      })}
    </div>
  );
}
