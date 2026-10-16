import React from "react";
import { createRoot } from "react-dom/client";
import { App } from "./App";
// Interface face (SIL Open Font License) and reading face for the chat and headings, both
// served with the app: nothing is fetched from a third party.
import "@fontsource-variable/figtree";
import "@fontsource-variable/source-serif-4/opsz.css";
import "./style.css";

createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>,
);
