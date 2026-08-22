import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { createBrowserRouter, RouterProvider } from "react-router";
// Self-hosted variable fonts (sovereignty: no external font host at runtime).
import "@fontsource-variable/geist";
import "@fontsource-variable/geist-mono";
import App from "./App";
import AuthCallback from "./views/AuthCallback";
import { LangProvider } from "./lib/lang";
import AdminView from "./views/AdminView";
import ChatView from "./views/ChatView";
import LandingView from "./views/LandingView";
import "./index.css";

// "/" locally; "/<repo>/" when built for GitHub Pages (--base flag).
const basename = import.meta.env.BASE_URL.replace(/\/$/, "") || "/";

const router = createBrowserRouter(
  [
    // The landing is public: it must render without an API key, so it lives
    // outside the App shell (which owns the key modal).
    { path: "/", element: <LandingView /> },
    { path: "auth/callback", element: <AuthCallback /> },
    {
      element: <App />,
      children: [
        { path: "chat", element: <ChatView /> },
        { path: "admin", element: <AdminView /> },
      ],
    },
  ],
  { basename },
);

const rootElement = document.getElementById("root");
if (rootElement === null) {
  throw new Error("index.html is missing the #root element");
}

createRoot(rootElement).render(
  <StrictMode>
    <LangProvider>
      <RouterProvider router={router} />
    </LangProvider>
  </StrictMode>,
);
