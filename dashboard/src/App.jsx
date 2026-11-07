import { useEffect, useState } from "react";

const TYPES = [
  { key: "chatbot", label: "Chatbots" },
  { key: "data_transfer", label: "Data transfer" },
  { key: "key_leak", label: "Key leaks" },
  { key: "disclosure", label: "Disclosure" },
  { key: "agent_ready", label: "Agent ready" },
];

const SEVERITY_ORDER = { high: 0, medium: 1, low: 2, info: 3 };

const COUNTRIES = {
  US: "United States", CA: "Canada", GB: "United Kingdom", FR: "France", DE: "Germany",
  PL: "Poland", ES: "Spain", IE: "Ireland", NL: "Netherlands", IT: "Italy", SE: "Sweden",
  CN: "China", IL: "Israel", IN: "India", AU: "Australia",
};

function countryName(code) {
  return COUNTRIES[code] || code || "Unknown";
}

function bySeverity(a, b) {
  return (SEVERITY_ORDER[a.severity] ?? 9) - (SEVERITY_ORDER[b.severity] ?? 9);
}

function countSeverity(findings, severity) {
  return findings.filter((f) => f.severity === severity).length;
}

function worstFinding(findings) {
  const real = findings.filter((f) => f.severity !== "info");
  return [...(real.length ? real : findings)].sort(bySeverity)[0];
}

function formatTime(iso) {
  if (!iso) return "";
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? iso : d.toLocaleString();
}

function scoreBand(score) {
  if (score === null || score === undefined) return "none";
  if (score >= 80) return "good";
  if (score >= 50) return "fair";
  return "poor";
}

function Score({ score, large }) {
  const empty = score === null || score === undefined;
  return (
    <span className={`score score-${scoreBand(score)}${large ? " score-large" : ""}`}>
      {empty ? "Couldn't scan" : score}
    </span>
  );
}

function dataDestinations(sites) {
  const byCountry = {};
  for (const site of sites) {
    for (const f of site.findings || []) {
      const meta = f.meta || {};
      const counts = f.type === "data_transfer" || (f.type === "chatbot" && meta.eu === true);
      if (!counts || !meta.country) continue;
      const row = (byCountry[meta.country] ||= {
        country: meta.country,
        eu: meta.eu === true,
        sites: new Set(),
        vendors: new Set(),
      });
      row.sites.add(site.site);
      if (meta.vendor) row.vendors.add(meta.vendor);
    }
  }
  return Object.values(byCountry).sort((a, b) => b.sites.size - a.sites.size);
}

function Overview({ data, onSelect }) {
  const sites = data.sites || [];
  const all = sites.flatMap((s) => s.findings || []);
  const destinations = dataDestinations(sites);
  const maxSites = Math.max(1, ...destinations.map((d) => d.sites.size));

  return (
    <>
      <section className="cards" aria-label="Findings by type">
        {TYPES.map((t) => (
          <div className="card total" key={t.key}>
            <div className="total-count">{all.filter((f) => f.type === t.key).length}</div>
            <div className="total-label">{t.label}</div>
          </div>
        ))}
      </section>

      <section className="panel">
        <h2>Where the data likely goes</h2>
        <p className="muted">
          Based on where each chat or AI vendor has its headquarters. Your own account may be set up to keep data in the EU.
        </p>
        {destinations.length === 0 ? (
          <p className="muted">No chat or AI vendors found.</p>
        ) : (
          <ul className="destinations">
            {destinations.map((d) => (
              <li key={d.country}>
                <div className="destination-head">
                  <span className="destination-name">{countryName(d.country)}</span>
                  <span className={`tag ${d.eu ? "tag-eu" : "tag-outside"}`}>
                    {d.eu ? "Inside the EU" : "Likely outside the EU"}
                  </span>
                  <span className="muted destination-count">
                    {d.sites.size} {d.sites.size === 1 ? "site" : "sites"}
                  </span>
                </div>
                <div className="bar">
                  <div
                    className={`bar-fill ${d.eu ? "bar-eu" : "bar-outside"}`}
                    style={{ width: `${(d.sites.size / maxSites) * 100}%` }}
                  />
                </div>
                <div className="muted small">{[...d.vendors].join(", ")}</div>
              </li>
            ))}
          </ul>
        )}
      </section>

      <section className="panel">
        <h2>Sites</h2>
        <table className="sites">
          <thead>
            <tr>
              <th>Site</th>
              <th>Score</th>
              <th>High</th>
              <th>Medium</th>
              <th>Most important finding</th>
            </tr>
          </thead>
          <tbody>
            {sites.map((s) => {
              const findings = s.findings || [];
              const worst = worstFinding(findings);
              return (
                <tr
                  key={s.site}
                  tabIndex={0}
                  onClick={() => onSelect(s.site)}
                  onKeyDown={(e) => (e.key === "Enter" || e.key === " ") && (e.preventDefault(), onSelect(s.site))}
                >
                  <td data-label="Site" className="site-name">{s.site}</td>
                  <td data-label="Score"><Score score={s.score} /></td>
                  <td data-label="High">{countSeverity(findings, "high")}</td>
                  <td data-label="Medium">{countSeverity(findings, "medium")}</td>
                  <td data-label="Most important" className="worst">
                    {s.error ? <span className="muted">{s.error}</span> : worst ? worst.title : <span className="muted">Nothing found</span>}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </section>
    </>
  );
}

function CopyButton({ text }) {
  const [copied, setCopied] = useState(false);
  async function copy() {
    try {
      await navigator.clipboard.writeText(text);
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    } catch {
      setCopied(false);
    }
  }
  return (
    <button type="button" className="button button-small" onClick={copy}>
      {copied ? "Copied" : "Copy"}
    </button>
  );
}

function FindingCard({ f }) {
  const where = f.evidence?.where || "";
  const isLink = /^https?:\/\//.test(where);
  const judged = f.method === "judged";
  return (
    <article className="card finding">
      <div className="finding-head">
        <h4>{f.title}</h4>
        <div className="badges">
          <span className={`pill pill-${f.severity}`}>{f.severity}</span>
          <span
            className={`method ${judged ? "method-judged" : "method-detected"}`}
            title={judged ? "A model or rule decided this; check it" : "Found by plain code"}
          >
            {f.method}
          </span>
        </div>
      </div>
      <div className="evidence">
        <div className="evidence-label">Evidence</div>
        {isLink ? (
          <a href={where} target="_blank" rel="noreferrer noopener">{where}</a>
        ) : (
          <span>{where}</span>
        )}
        {f.evidence?.snippet && <pre className="snippet"><code>{f.evidence.snippet}</code></pre>}
      </div>
      {f.fix && (
        <div className="fix">
          <div className="fix-head">
            <strong>What to tell your web person</strong>
            <CopyButton text={f.fix} />
          </div>
          <p>{f.fix}</p>
        </div>
      )}
    </article>
  );
}

function SiteView({ site, onBack }) {
  const findings = site.findings || [];
  return (
    <>
      <button type="button" className="button" onClick={onBack}>← Back to all sites</button>
      <section className="panel site-head">
        <div>
          <h2>{site.site}</h2>
          {site.final_url && (
            <a href={site.final_url} target="_blank" rel="noreferrer noopener">{site.final_url}</a>
          )}
        </div>
        <Score score={site.score} large />
      </section>
      {site.error && (
        <div className="banner" role="alert">
          We couldn't scan this site: {site.error}
        </div>
      )}
      {TYPES.map((t) => {
        const group = findings.filter((f) => f.type === t.key).sort(bySeverity);
        return (
          <section className="group" key={t.key}>
            <h3>{t.label}</h3>
            {group.length === 0 ? (
              <p className="muted">Nothing found</p>
            ) : (
              group.map((f) => <FindingCard f={f} key={f.id} />)
            )}
          </section>
        );
      })}
    </>
  );
}

export default function App() {
  const [data, setData] = useState(null);
  const [loadError, setLoadError] = useState(null);
  const [selected, setSelected] = useState(null);

  useEffect(() => {
    fetch("/findings.json")
      .then((r) => {
        if (!r.ok) throw new Error(`findings.json returned ${r.status}`);
        return r.json();
      })
      .then(setData)
      .catch((e) => setLoadError(e.message));
  }, []);

  function select(name) {
    setSelected(name);
    window.scrollTo(0, 0);
  }

  const site = data && selected ? (data.sites || []).find((s) => s.site === selected) : null;

  return (
    <div className="page">
      <header className="header">
        <h1>AI Exposure Scan</h1>
        {data && (
          <p className="muted">
            Scanned {formatTime(data.generated_at)} · {(data.sites || []).length}{" "}
            {(data.sites || []).length === 1 ? "site" : "sites"}
          </p>
        )}
      </header>
      <main>
        {loadError && <div className="banner" role="alert">Couldn't load the scan results ({loadError}).</div>}
        {!data && !loadError && <p className="muted">Loading…</p>}
        {data && (site ? <SiteView site={site} onBack={() => select(null)} /> : <Overview data={data} onSelect={select} />)}
      </main>
    </div>
  );
}
