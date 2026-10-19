import { useEffect } from "react";

export function usePageTitle(title?: string) {
  useEffect(() => {
    document.title = title ? `${title} · Post Pilot` : "Post Pilot";
  }, [title]);
}
