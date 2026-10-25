import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { App } from "./App";
import "./styles.css";

// ?internal=1 marks this browser as the site owner's, so Image Label's usage counts leave it out
// (?internal=0 undoes it). A cookie, so every request carries it; it holds nothing else.
const internal = new URLSearchParams(location.search).get("internal");
if (internal === "1") document.cookie = "internal=1; max-age=34560000; path=/; secure; samesite=lax";
if (internal === "0") document.cookie = "internal=; max-age=0; path=/; secure; samesite=lax";

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <App />
  </StrictMode>,
);
