import "@fontsource/sofia-sans-semi-condensed/latin-400.css";
import "@fontsource/sofia-sans-semi-condensed/latin-500.css";
import "@fontsource/sofia-sans-semi-condensed/latin-600.css";
import "@fontsource/sofia-sans-semi-condensed/latin-700.css";
import "@fontsource/red-hat-mono/latin-400.css";
import "@fontsource/red-hat-mono/latin-500.css";
import "@fontsource/red-hat-mono/latin-600.css";
import "./styles/tokens.css";
import "./styles/base.css";
import "./styles/shell.css";
import "./styles/components.css";

import { StrictMode } from "react";
import { createRoot } from "react-dom/client";

import { App } from "./app/App";

const root = document.getElementById("root");
if (!root) throw new Error("index.html has no #root element");

createRoot(root).render(
  <StrictMode>
    <App />
  </StrictMode>,
);
