import { render } from "preact";

import { DoctorBanner } from "./components/Banners";
import { History } from "./components/History";
import { PostingPreview } from "./components/Preview";
import { refreshHistory, resumeIfRunning, showRun } from "./run";
import { refreshDoctor } from "./state";
import { GenerateForm } from "./views/Generate";
import { RunView } from "./views/Run";
import "./styles.css";

function App() {
  // The form wants the extra width only while the preview is beside it. A report is prose and
  // a table, and both read worse the wider they get.
  const composing = !showRun.value;

  return (
    <div class={composing ? "app app-wide" : "app"}>
      <header class="topbar">
        <h1>resume-fill</h1>
        <p class="tagline">
          Nothing it writes is invented. Every bullet carries the id of the source it came from.
        </p>
      </header>

      <main>
        <DoctorBanner />
        {composing ? (
          <div class="layout">
            <GenerateForm />
            <PostingPreview />
          </div>
        ) : (
          <RunView />
        )}
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
