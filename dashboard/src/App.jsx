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
    <span
      className={`score score-${scoreBand(score)}${large ? " score-large" : ""}`}
      style={large && !empty ? { "--score": score } : undefined}
    >
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
          <div className="card total" data-type={t.key} key={t.key}>
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
                  <td data-label="Site" className="site-name">{s.label || s.site}</td>
                  <td data-label="Score"><Score score={s.score} /></td>
                  <td data-label="High">{s.error ? "–" : countSeverity(findings, "high")}</td>
                  <td data-label="Medium">{s.error ? "–" : countSeverity(findings, "medium")}</td>
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

function hostOf(url) {
  try {
    return new URL(url).host;
  } catch {
    return "";
  }
}

function pathOf(url) {
  try {
    return new URL(url).pathname;
  } catch {
    return "";
  }
}

function howWeKnow(f, site) {
  const where = f.evidence?.where || "";
  const snippet = f.evidence?.snippet || "";
  const host = hostOf(where);
  const file = pathOf(where).split("/").pop();
  const homepage = site.final_url && where.replace(/\/$/, "") === site.final_url.replace(/\/$/, "");
  const missing = /not found/i.test(snippet);
  const slug = (f.id || "").split(":").pop();

  if (file === "robots.txt") {
    return missing
      ? "We asked for the site's robots.txt file and there wasn't one."
      : "Found in the site's robots.txt file, which tells bots what they may read.";
  }
  if (file === "llms.txt") {
    return missing
      ? "We asked for the site's llms.txt file and there wasn't one."
      : "Found in the site's llms.txt file, a short guide written for AI assistants.";
  }
  if (f.type === "data_transfer") {
    const vendor = f.meta?.vendor || "this vendor";
    const seen = /^[A-Z]+ https?:\/\//.test(snippet)
      ? `We saw the homepage contact ${vendor} while loading.`
      : `We spotted ${vendor} in the homepage code.`;
    return `${seen} Where it's based comes from our list of AI vendors.`;
  }
  if (f.type === "disclosure") {
    if (slug === "no-policy") return "We looked on the homepage for a link to a privacy policy and found none.";
    if (slug.startsWith("bot-") && /^no chat greeting/i.test(snippet)) {
      return "We looked for the chat greeting on the homepage and couldn't see it without opening the chat.";
    }
    if (slug.startsWith("bot-")) return "Read from the chat greeting text on the homepage.";
    return "Read from the site's privacy policy.";
  }
  if (snippet.startsWith("<script")) return `Found in a script loaded from ${host}.`;
  if (/^(GET|POST|PUT|PATCH|DELETE|OPTIONS|HEAD) /.test(snippet)) {
    return `Seen when the page contacted ${host} while loading.`;
  }
  if (f.type === "agent_ready" && slug === "mcp" && homepage) return "Found on the homepage, where the site names it.";
  if (where === "inline script" || homepage) return "Found in code written into the homepage.";
  if (host && f.type === "key_leak") return `Found in the file ${file || host}, which every visitor's browser downloads.`;
  if (host) return `Found in a file loaded from ${host}.`;
  return null;
}

function FindingCard({ f, site }) {
  const how = howWeKnow(f, site);
  const where = f.evidence?.where || "";
  const isLink = /^https?:\/\//.test(where);
  const judged = f.method === "judged";
  return (
    <article className="card finding" data-severity={f.severity}>
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
        {how && <p className="how">How we know: {how}</p>}
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
          <h2>{site.label || site.site}</h2>
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
      {!site.error && TYPES.map((t) => {
        const group = findings.filter((f) => f.type === t.key).sort(bySeverity);
        return (
          <section className="group" key={t.key}>
            <h3>{t.label}</h3>
            {group.length === 0 ? (
              <p className="muted">Nothing found</p>
            ) : (
              group.map((f, i) => <FindingCard f={f} site={site} key={f.id || `${t.key}-${i}`} />)
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
        {!site && (
          <p className="explainer">
            We visited each site once, like a normal visitor, and listed the AI it exposes. Nothing was hacked or tested.
          </p>
        )}
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
