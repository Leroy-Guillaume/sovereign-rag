import { Link } from "react-router";

/**
 * The "s sovereign-rag" brand block used by the chat sidebar and the admin
 * top bar. Logo-as-home is the convention; the hover swap to "< Site" makes
 * it visible.
 */
export default function BrandHomeLink() {
  return (
    <Link to="/" className="group flex h-5 items-center gap-2.5" aria-label="Retour au site">
      <span className="grid size-5 place-items-center rounded-md bg-ink text-[11px] font-semibold text-white group-hover:hidden">
        s
      </span>
      <span className="text-[13.5px] font-semibold tracking-tight group-hover:hidden">
        sovereign-rag
      </span>
      <span className="hidden text-[13px] font-medium text-link group-hover:inline">‹ Site</span>
    </Link>
  );
}
