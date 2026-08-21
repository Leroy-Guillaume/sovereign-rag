import { Link } from "react-router";

/**
 * The "s sovereign-rag" brand block used by the chat sidebar and the admin
 * top bar. Logo-as-home is the convention; the hover swap to "< Site" makes
 * it visible. The two states overlay in one fixed-size box: swapping with
 * display would shrink the hover target under the pointer and flicker.
 */
export default function BrandHomeLink() {
  return (
    <Link to="/" className="group relative flex h-5 items-center" aria-label="Retour au site">
      <span className="flex items-center gap-2.5 transition-opacity duration-150 group-hover:opacity-0">
        <span className="grid size-5 place-items-center rounded-md bg-ink text-[11px] font-semibold text-white">
          s
        </span>
        <span className="text-[13.5px] font-semibold tracking-tight">sovereign-rag</span>
      </span>
      <span className="absolute inset-y-0 left-0 flex items-center text-[13px] font-medium text-link opacity-0 transition-opacity duration-150 group-hover:opacity-100">
        ‹ Site
      </span>
    </Link>
  );
}
