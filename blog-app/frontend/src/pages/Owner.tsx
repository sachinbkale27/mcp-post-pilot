import { useState } from "react";
import { KeyRound } from "lucide-react";
import { ownerKey, setOwnerKey } from "../api";
import { useToast } from "../components/Feedback";
import { usePageTitle } from "../lib/usePageTitle";

/** Where the blog owner enters their key, to edit, unpublish or delete published posts in this tab. */
export function Owner() {
  usePageTitle("Owner");
  const notify = useToast();
  const [key, setKey] = useState("");
  const [saved, setSaved] = useState(!!ownerKey());

  return (
    <div className="container section owner-page">
      <h1><KeyRound size={22} aria-hidden /> Blog owner</h1>
      <p className="muted">
        Anyone can write drafts, and a post is published once the Fact-check agent finds every claim in it supported.
        Only the owner can change, unpublish or delete published posts, or publish without a check. The key is kept in
        this browser tab only and is forgotten when you close it.
      </p>
      {saved ? (
        <button className="btn btn-secondary" onClick={() => { setOwnerKey(""); setSaved(false); notify("success", "Signed out"); }}>
          Forget the key
        </button>
      ) : (
        <form onSubmit={(e) => { e.preventDefault(); setOwnerKey(key.trim()); setKey(""); setSaved(true); notify("success", "Owner key saved for this tab"); }}>
          <label className="field">
            <span>Owner key</span>
            <input type="password" autoComplete="off" value={key} onChange={(e) => setKey(e.target.value)} required />
          </label>
          <button className="btn btn-primary" type="submit">Use key</button>
        </form>
      )}
    </div>
  );
}
