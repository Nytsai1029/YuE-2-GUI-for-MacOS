import "./index.css";
import "./i18n";
import * as RTooltip from "@radix-ui/react-tooltip";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { StrictMode, useEffect } from "react";
import { createRoot } from "react-dom/client";
import { createBrowserRouter, RouterProvider } from "react-router-dom";
import { Shell } from "./components/Shell";
import { Catalog } from "./pages/Catalog";
import { Library } from "./pages/Library";
import { Queue } from "./pages/Queue";
import { SettingsPage } from "./pages/Settings";
import { SongPage } from "./pages/Song";
import { applyTheme, connectEvents, useUi } from "./store";

const qc = new QueryClient({ defaultOptions: { queries: { staleTime: 5000, refetchOnWindowFocus: false, retry: 1 } } });

const router = createBrowserRouter([
  {
    path: "/", element: <Shell />, children: [
      { index: true, element: <Library /> },
      { path: "song/:id", element: <SongPage /> },
      { path: "song/:id/:tab", element: <SongPage /> },
      { path: "queue", element: <Queue /> },
      { path: "checks", element: <Catalog /> },
      { path: "settings", element: <SettingsPage /> },
    ],
  },
]);

function App() {
  const theme = useUi((s) => s.theme);
  useEffect(() => applyTheme(theme), [theme]);
  useEffect(() => connectEvents(qc), []);
  return (
    <QueryClientProvider client={qc}>
      <RTooltip.Provider>
        <RouterProvider router={router} />
      </RTooltip.Provider>
    </QueryClientProvider>
  );
}

createRoot(document.getElementById("root")!).render(<StrictMode><App /></StrictMode>);
