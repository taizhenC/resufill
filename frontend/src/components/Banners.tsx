import { blockers, doctorError, doctorReport, refreshDoctor, warnings } from "../state";

/**
 * The preflight banner.
 *
 * `init`, `blog sync` and `linkedin draft` are CLI-only by design, so when the setup is
 * incomplete the browser cannot fix it — which means the banner's whole job is to name the
 * exact command that can. A broken setup must never look like a broken run.
 */
export function DoctorBanner() {
  if (doctorError.value) {
    return (
      <div class="banner banner-bad">
        <strong>No server.</strong> {doctorError.value}
      </div>
    );
  }

  const report = doctorReport.value;
  if (!report) return <div class="banner banner-muted">Checking your setup…</div>;

  return (
    <>
      {blockers.value.length > 0 && (
        <div class="banner banner-bad">
          <strong>Setup incomplete.</strong> Generation is disabled until these are fixed.
          <ul>
            {blockers.value.map((check) => (
              <li key={check.name}>
                {check.detail}
                {check.fix && (
                  <>
                    {" — "}
                    <code>{check.fix}</code>
                  </>
                )}
              </li>
            ))}
          </ul>
          <button class="link" onClick={() => void refreshDoctor()}>
            re-check
          </button>
        </div>
      )}

      {warnings.value.map((check) => (
        // Non-blocking on purpose: the tool is designed to work without a blog.
        <div class="banner banner-warn" key={check.name}>
          {check.detail}
          {check.fix && (
            <>
              {" — optional: "}
              <code>{check.fix}</code>
            </>
          )}
        </div>
      ))}
    </>
  );
}
