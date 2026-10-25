import { Faq, type FaqItem, Need, Optional } from "./Faq";

/** Short questions people ask before annotating their first image; each opens to a plain answer. */
const FAQ: FaqItem[] = [
  {
    q: "What is image annotation?",
    a: "Marking what is in an image: drawing an outline around each object and naming it, such as \"car\" or \"tumour cells\". Annotated images are used to train and test AI models, and to measure and explain what an image shows.",
  },
  {
    q: "What does this page do?",
    a: "You give it an image and say what to mark. The Image Annotation Agent finds each object and Segment Anything traces its exact outline. You can then download the outlines as training data, or open them in Image Label to edit.",
  },
  {
    q: "Which fields must I fill in?",
    a: (
      <ul>
        <li><strong>Image</strong> <Need /> Upload a file or paste an image URL, one or the other.</li>
        <li><strong>What to label</strong> <Need /> Needed for Annotate; the histology tools and Diagnose work without it.</li>
        <li><strong>Label names</strong> <Optional /> The names to use for the outlines.</li>
        <li><strong>Image type</strong> <Optional /> Starts on "Photo or general image"; change it for medical scans.</li>
      </ul>
    ),
  },
  {
    q: "What should I write in \"What to label\"?",
    a: (
      <>
        Say plainly what to outline, for example "Outline every person and every car" or "Circle the tumour regions".
        <br /><strong>Label names</strong> <Optional /> keep the names the same across many images, so a dataset stays consistent.
      </>
    ),
  },
  {
    q: "Photo or medical scan?",
    a: "Choose \"Photo or general image\" for everyday pictures (SAM). Choose \"Medical scan\" for CT, MRI, X-ray, ultrasound, endoscopy or pathology images (MedSAM, a version of Segment Anything trained on medical images).",
  },
  {
    q: "What are the histology tools?",
    a: (
      <ul>
        <li><strong>Check quality</strong>: looks for blur, marker pen, poor exposure, faint staining and too little tissue.</li>
        <li><strong>Detect nuclei</strong>: finds and outlines every cell nucleus automatically (StarDist), and measures their sizes.</li>
        <li><strong>Normalize stain</strong>: evens out the pink and purple colours, so slides from different labs look alike. The result is saved as a new image.</li>
      </ul>
    ),
  },
  {
    q: "What do the cell types mean?",
    a: (
      <>
        After <strong>Detect nuclei</strong>, <strong>Cell types</strong> sorts each nucleus into one of five groups
        (HoVer-Net, a model trained on 19 tissues): <strong>tumour</strong>, <strong>immune</strong> (mostly
        lymphocytes), <strong>connective tissue</strong>, <strong>dead</strong> and <strong>normal epithelial</strong>.
        The immune-to-tumour ratio is a rough sign of how much the immune system has moved into a tumour. These are
        model estimates for research and education, not a diagnosis, and the model's licence doesn't allow
        commercial use.
      </>
    ),
  },
  {
    q: "What is an H&E slide?",
    a: "A thin slice of tissue stained with two dyes: haematoxylin colours cell nuclei purple, and eosin colours the rest pink. It is the most common stain in pathology. The histology tools are made for these images.",
  },
  {
    q: "What are \"enlarged nuclei\"?",
    a: "Nuclei more than 2.5 times the typical size in the image. Large and uneven nuclei are one thing pathologists look at, but on their own they are a measurement, not a diagnosis.",
  },
  {
    q: "What do Diagnose and Ask AI do?",
    a: "Diagnose gives an AI interpretation of the image and outlines the regions it is concerned about. Ask AI opens the genetics assistant with these results, so you can ask what they mean. Both are for research and learning.",
  },
  {
    q: "Which download should I use?",
    a: (
      <ul>
        <li><strong>COCO JSON</strong>: works with most training tools, and with Image Label's Import.</li>
        <li><strong>YOLO labels</strong> and <strong>YOLO classes</strong>: for YOLO models such as Ultralytics. Keep both files.</li>
        <li><strong>QuPath GeoJSON</strong>: for pathology work in QuPath (File &gt; Import objects).</li>
        <li><strong>Annotated image (PNG)</strong>: a picture with the outlines and labels, for reports and slides.</li>
      </ul>
    ),
  },
  {
    q: "An outline is wrong. Can I fix it?",
    a: "Yes. Download the image and the COCO annotations, open Image Label, upload the image, and press Import: the outlines appear, ready to edit and export again. Dashed outlines scored low, so check those first.",
  },
  {
    q: "How long does it take?",
    a: "Labelling usually takes 10 to 30 seconds. After a quiet spell, the first histology tool run can take up to a minute while the model starts.",
  },
  {
    q: "What does \"Start over\" do?",
    a: "It clears the image and the results from this page, so you can begin with a new image. Your instructions stay, and anything already saved in Image Label is kept.",
  },
  {
    q: "Is my image private?",
    a: "Images are stored online so the tools can read them. Don't upload pictures that show names, record numbers or faces of patients. Remove that information first.",
  },
  {
    q: "Is this medical advice?",
    a: "No. The outlines, measurements and interpretations are AI outputs for research, datasets and education. Only a qualified doctor or pathologist can make a diagnosis.",
  },
];

export function AnnotateFaq() {
  return <Faq title="Questions about image annotation" items={FAQ} />;
}
