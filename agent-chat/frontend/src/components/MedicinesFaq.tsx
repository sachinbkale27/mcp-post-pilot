import { Faq, type FaqItem, Need, Optional } from "./Faq";

/** Short questions people ask before looking up a medicine; each opens to a plain answer. */
const FAQ: FaqItem[] = [
  {
    q: "Where does this information come from?",
    a: (
      <ul>
        <li><strong>FDA drug labels</strong>: the official prescribing information (openFDA, DailyMed).</li>
        <li><strong>Reports to the FDA</strong>: side effects people and doctors reported (FAERS).</li>
        <li><strong>FDA recalls</strong>: batches taken off the market.</li>
        <li><strong>RxNorm</strong> (US National Library of Medicine): matches brand and generic names, and fixes spelling.</li>
      </ul>
    ),
  },
  {
    q: "Which fields must I fill in?",
    a: (
      <ul>
        <li><strong>Medicine</strong> <Need /> A brand or generic name, e.g. Ozempic or metformin.</li>
        <li><strong>What do you want to know?</strong> <Optional /> Starts on uses, side effects and warnings.</li>
        <li><strong>Other medicines, food or alcohol</strong> <Optional /> To check what the label says about taking them together.</li>
        <li><strong>Your question</strong> <Optional /> Anything else, in your own words.</li>
      </ul>
    ),
  },
  {
    q: "What is a drug label?",
    a: "The official information approved by the US Food and Drug Administration (FDA) for each medicine: what it treats, how it is taken, warnings, side effects and interactions. It is the long leaflet that comes with the medicine.",
  },
  {
    q: "Brand name or generic name?",
    a: "Either works. The generic name is the active ingredient (semaglutide); brand names are what companies call their product (Ozempic, Wegovy). Names differ between countries: paracetamol is called acetaminophen in the US.",
  },
  {
    q: "My medicine is sold outside the US. Will this work?",
    a: "Usually, if you enter the generic name: the same ingredient has much the same label everywhere. A medicine sold only outside the US may not be found, and strengths or brands can differ from yours.",
  },
  {
    q: "What is a boxed warning?",
    a: "The FDA's most serious kind of warning, printed in a box at the top of the label. It is shown first when a medicine has one.",
  },
  {
    q: "What do \"reports to the FDA\" mean?",
    a: "Anyone can report a problem they noticed while taking a medicine. A report doesn't prove the medicine caused it, and counts don't show how common it is: widely used medicines get more reports.",
  },
  {
    q: "What is a recall?",
    a: "Taking certain batches off the market, for example for contamination or a wrong strength. Class I is the most serious. A recall usually affects some batches, not every pack.",
  },
  {
    q: "Why does every point have a quote?",
    a: "So you can see each point is in the label itself. The agent can only file points whose quote is found in the label it read, and the DailyMed link opens the full label.",
  },
  {
    q: "The label doesn't mention my other medicine. Is it safe?",
    a: "Not necessarily. Labels list known and important interactions, not every combination. Ask a pharmacist, who can check all your medicines together.",
  },
  {
    q: "Can it tell me what dose to take?",
    a: "No. It can describe the usual dosing in the label, but your dose depends on you, so only your doctor can set it.",
  },
  {
    q: "Is this medical advice?",
    a: "No. It explains official information. Ask your doctor or pharmacist before starting, stopping or changing a medicine.",
  },
];

export function MedicinesFaq() {
  return <Faq title="Questions about medicine information" items={FAQ} />;
}
