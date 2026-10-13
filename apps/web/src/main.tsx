import React from "react";
import { createRoot } from "react-dom/client";
import { App } from "./App";
// Reading face for the chat (SIL Open Font License), served with the app.
import "@fontsource-variable/source-serif-4/opsz.css";
import "./style.css";
import "./ocean.css";

createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>,
);
