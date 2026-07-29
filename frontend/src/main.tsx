import { render } from "preact";

import { DoctorBanner } from "./components/Banners";
import { History } from "./components/History";
import { refreshHistory, resumeIfRunning, showRun } from "./run";
import { refreshDoctor } from "./state";
import { GenerateForm } from "./views/Generate";
import { RunView } from "./views/Run";
import "./styles.css";

function App() {
  return (
    <div class="app">
      <header class="topbar">
        <h1>resume-fill</h1>
        <p class="tagline">
          Nothing it writes is invented. Every bullet carries the id of the source it came from.
        </p>
      </header>

      <main>
        <DoctorBanner />
        {showRun.value ? <RunView /> : <GenerateForm />}
        <History />
      </main>

      <footer class="footer">
        Local only — this page talks to <code>resume-fill serve</code> on your machine.
      </footer>
    </div>
  );
}

void refreshDoctor();
void refreshHistory();
// A page reload during a run should resume watching it rather than pretend it is not there.
void resumeIfRunning();

render(<App />, document.getElementById("app")!);
