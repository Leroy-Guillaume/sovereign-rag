// Build-time flags (Vite env). VITE_STATIC_LANDING=1 marks the GitHub Pages
// build: only the landing is served there, so in-app links must point at the
// repository instead of routes that have no backend behind them.
export const staticLanding = import.meta.env.VITE_STATIC_LANDING === "1";
