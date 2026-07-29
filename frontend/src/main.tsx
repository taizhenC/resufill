import { render } from "preact";

import { DoctorBanner } from "./components/Banners";
import { refreshDoctor } from "./state";
import { GenerateForm } from "./views/Generate";
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
        <GenerateForm />
      </main>

      <footer class="footer">
        Local only — this page talks to <code>resume-fill serve</code> on your machine.
      </footer>
    </div>
  );
}

void refreshDoctor();
render(<App />, document.getElementById("app")!);
