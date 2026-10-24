import { Faq, type FaqItem } from "./Faq";

/** Short questions an ordinary patient asks first; each opens to a plain answer. */
const FAQ: FaqItem[] = [
  {
    q: "What is a clinical trial?",
    a: "A research study that tests a new treatment, test or way of caring for people, to see whether it is safe and works better than what is used today.",
  },
  {
    q: "Why would I look for one?",
    a: (
      <ul>
        <li>New treatments, years before they are approved or affordable.</li>
        <li>An option when standard treatment has stopped working, or there is none.</li>
        <li>The trial treatment, and often tests and scans, are usually free.</li>
        <li>Close follow-up by specialists at major hospitals.</li>
        <li>Helping future patients.</li>
      </ul>
    ),
  },
  {
    q: "Is it safe? What are the risks?",
    a: "Trials are approved and watched by ethics committees and regulators. Still, a new treatment may have unknown side effects, or work no better than the standard one. The trial team explains the risks before you agree.",
  },
  {
    q: "Will I get the new treatment?",
    a: "Not always. In many trials a computer decides at random who gets the new treatment and who gets the standard one, so the two can be compared fairly. You still get proper care either way.",
  },
  {
    q: "Does it cost anything?",
    a: "The treatment being tested is usually free, and some trials cover tests or travel. Ask the trial team what is paid for.",
  },
  {
    q: "Can I leave?",
    a: "Yes, at any time and for any reason, without losing your normal care.",
  },
  {
    q: "Who can join?",
    a: "Each trial has rules (age, type and stage of disease, past treatments, other illnesses). This page shows which rules may matter, but only the trial team can confirm that you can join.",
  },
  {
    q: "What does \"phase\" mean?",
    a: "How far a new treatment has got: phase 1 checks safety, phase 2 whether it works, phase 3 compares it with the standard treatment, phase 4 follows it after approval.",
  },
  {
    q: "What is a lab test result?",
    a: "For many cancers, a test on the tumour shows which type it is, for example \"HER2-positive\" breast cancer. Some new drugs only work on one type, so trials often accept only that type. It is on your pathology or genetic test report.",
  },
  {
    q: "Can a gene change?",
    a: "Yes. Some changes (mutations) are inherited and in every cell. Most cancer-related ones happen during life, only in the tumour cells, which is why the test is done on the tumour. Some drugs target exactly that change.",
  },
  {
    q: "I found a trial. What next?",
    a: "Show it to your doctor. Then contact the trial site through the ClinicalTrials.gov link on the card: they check whether you can join and explain everything before you decide.",
  },
  {
    q: "Is this medical advice?",
    a: "No. This page searches a public registry and explains what it finds. Decisions about treatment are for you and your doctor.",
  },
];

export function TrialsFaq() {
  return <Faq title="Questions about clinical trials" items={FAQ} />;
}
