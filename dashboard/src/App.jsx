import { useEffect, useState } from "react";

// Static build for the public demo (GitHub Pages): sample data only, no scan server.
const DEMO = import.meta.env.VITE_DEMO === "1";
const REPO_URL = "https://github.com/AIwithDiego/ai-exposure-scan";

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
  CN: "China", IL: "Israel", IN: "India", AU: "Australia", AT: "Austria", BE: "Belgium",
  BG: "Bulgaria", HR: "Croatia", CY: "Cyprus", CZ: "Czechia", DK: "Denmark", EE: "Estonia",
  FI: "Finland", GR: "Greece", HU: "Hungary", LV: "Latvia", LT: "Lithuania", LU: "Luxembourg",
  MT: "Malta", PT: "Portugal", RO: "Romania", SK: "Slovakia", SI: "Slovenia", CH: "Switzerland",
  NO: "Norway", IS: "Iceland", NZ: "New Zealand", SG: "Singapore", JP: "Japan", HK: "Hong Kong",
  BR: "Brazil", ZA: "South Africa", KR: "South Korea", AR: "Argentina",
};

const EU_COUNTRIES = new Set([
  "AT", "BE", "BG", "HR", "CY", "CZ", "DK", "EE", "FI", "FR", "DE", "GR", "HU", "IE",
  "IT", "LV", "LT", "LU", "MT", "NL", "PL", "PT", "RO", "SK", "SI", "ES", "SE",
]);

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

function addDestination(byCountry, site, country, eu, name) {
  const row = (byCountry[country] ||= { country, eu: eu === true, sites: new Set(), vendors: new Set() });
  row.sites.add(site.site);
  if (name) row.vendors.add(name);
}

function sortDestinations(byCountry) {
  return Object.values(byCountry).sort((a, b) => b.sites.size - a.sites.size || b.vendors.size - a.vendors.size);
}

function dataDestinations(sites) {
  const byCountry = {};
  for (const site of sites) {
    for (const f of site.findings || []) {
      const meta = f.meta || {};
      if (meta.kind) continue;
      const counts = f.type === "data_transfer" || (f.type === "chatbot" && meta.eu === true);
      if (!counts || !meta.country) continue;
      addDestination(byCountry, site, meta.country, meta.eu, meta.vendor);
    }
  }
  return sortDestinations(byCountry);
}

function serviceDestinations(sites) {
  const byCountry = {};
  for (const site of sites) {
    const f = servicesFinding(site);
    for (const svc of f?.meta?.services || []) {
      if (svc.country) addDestination(byCountry, site, svc.country, svc.eu, svc.name);
    }
  }
  return sortDestinations(byCountry);
}

function metaFinding(site, kind) {
  return (site.findings || []).find((f) => f.type === "data_transfer" && f.meta?.kind === kind);
}

function servicesFinding(site) {
  return metaFinding(site, "services");
}

function hostingLine(site) {
  const meta = metaFinding(site, "hosting")?.meta;
  if (!meta?.ip_country) return null;
  const code = meta.ip_country;
  const eu = EU_COUNTRIES.has(code);
  if (meta.cdn) {
    if (!meta.edge_city) return { text: `Served through ${meta.cdn}'s global network · real server may differ`, eu: null };
    const edgeEu = EU_COUNTRIES.has(meta.edge_country);
    const where = edgeEu ? "EU" : meta.edge_country === "GB" ? "UK" : meta.edge_country;
    return { text: `Served through ${meta.cdn} from ${meta.edge_city} (${where}) · real server may differ`, eu: edgeEu };
  }
  return { text: `Hosted in ${countryName(code)} · ${eu ? "inside the EU" : "likely outside the EU"}`, eu };
}

function DestinationList({ rows, quiet }) {
  const maxSites = Math.max(1, ...rows.map((d) => d.sites.size));
  return (
    <ul className={`destinations${quiet ? " destinations-quiet" : ""}`}>
      {rows.map((d) => (
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
  );
}

function Overview({ data, onSelect }) {
  const sites = data.sites || [];
  const all = sites.flatMap((s) => s.findings || []);
  const destinations = dataDestinations(sites);
  const services = serviceDestinations(sites);

  return (
    <>
      <section className="cards" aria-label="Findings by type">
        {TYPES.map((t) => (
          <div className="card total" key={t.key} data-type={t.key}>
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
          <DestinationList rows={destinations} />
        )}
        {services.length > 0 && (
          <div className="destinations-group">
            <h3>Other services</h3>
            <p className="muted small">
              Analytics, ads, fonts, videos and other tools the homepages load, by where each company is based.
            </p>
            <DestinationList rows={services} quiet />
          </div>
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
  if (f.type === "data_transfer" && f.meta?.kind === "hosting") {
    const base = "We noted the address of the server that answered when the homepage loaded and looked up its country in the DB-IP database.";
    return f.meta.cdn
      ? `We saw from the reply's headers that it came through ${f.meta.cdn}, which answers from a city near the visitor${f.meta.edge_city ? `; the headers name ${f.meta.edge_city} as the answering location` : ""}. The real server can be elsewhere.`
      : base;
  }
  if (f.type === "data_transfer" && f.meta?.kind === "services") {
    return "We listed the other websites the homepage contacted while loading and matched them to our list of common services. Where each company is based comes from that list.";
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

const CATEGORIES = {
  analytics: "Analytics", ads: "Ads", crm: "CRM", social: "Social", video: "Video", fonts: "Fonts",
  cdn: "CDN", consent: "Consent", payments: "Payments", maps: "Maps",
};

function ServicesList({ meta }) {
  const services = meta.services || [];
  const unknown = meta.unknown_domains || [];
  if (!services.length && !unknown.length) return null;
  return (
    <div className="services">
      {services.length > 0 && (
        <ul className="services-list">
          {services.map((s) => (
            <li key={s.name}>
              <span className="service-name">{s.name}</span>
              <span className="muted service-category">{CATEGORIES[s.category] || s.category}</span>
              <span className="muted service-country">{countryName(s.country)}</span>
              <span className={`tag ${s.eu ? "tag-eu" : "tag-outside"}`}>{s.eu ? "EU" : "Likely outside the EU"}</span>
            </li>
          ))}
        </ul>
      )}
      {unknown.length > 0 && (
        <p className="muted small services-unknown">Also contacted: {unknown.join(", ")}</p>
      )}
    </div>
  );
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
      {f.meta?.kind === "services" && <ServicesList meta={f.meta} />}
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
  const hosted = hostingLine(site);
  return (
    <>
      <button type="button" className="button" onClick={onBack}>← Back to all sites</button>
      <section className="panel site-head">
        <div>
          <h2>{site.label || site.site}</h2>
          {hosted && (
            <p className={`site-hosting ${hosted.eu === null ? "" : hosted.eu ? "hosting-eu" : "hosting-outside"}`}>{hosted.text}</p>
          )}
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

function scanHost(text) {
  const value = text.trim();
  try {
    return new URL(/^[a-z][a-z0-9+.-]*:\/\//i.test(value) ? value : `https://${value}`).host || value;
  } catch {
    return value;
  }
}

function DemoScanBar() {
  return (
    <section className="scan" aria-label="Scan a website">
      <div className="scan-bar">
        <label htmlFor="scan-url" className="visually-hidden">Website to scan</label>
        <input
          id="scan-url"
          className="scan-input"
          type="text"
          placeholder="Scanning runs on your machine"
          disabled
        />
        <a className="button scan-button" href={`${REPO_URL}#run-it-yourself`}>Run it yourself</a>
      </div>
      <p className="muted small demo-note">
        Live demo with sample data: a fake café scanned by the real pipeline, plus made-up sites. No real website appears here.
      </p>
    </section>
  );
}

function ScanBar({ onScanned }) {
  const [url, setUrl] = useState("");
  const [scanning, setScanning] = useState(null);
  const [error, setError] = useState(null);

  async function submit(e) {
    e.preventDefault();
    const value = url.trim();
    if (!value || scanning) return;
    setError(null);
    setScanning(scanHost(value));
    try {
      const r = await fetch("/api/scan", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ url: value }),
      });
      if (!r.ok) {
        const text = (await r.text()).trim();
        throw new Error(text && !text.startsWith("<") ? text : `The scan server returned ${r.status}.`);
      }
      const entry = await r.json();
      setUrl("");
      onScanned(entry);
    } catch (err) {
      setError(err instanceof TypeError ? "Couldn't reach the scan server. Is it running?" : err.message);
    } finally {
      setScanning(null);
    }
  }

  return (
    <section className="scan" aria-label="Scan a website">
      <form className="scan-bar" onSubmit={submit}>
        <label htmlFor="scan-url" className="visually-hidden">Website to scan</label>
        <input
          id="scan-url"
          className="scan-input"
          type="text"
          inputMode="url"
          autoComplete="off"
          spellCheck="false"
          placeholder="Enter a website, e.g. example.ie"
          value={url}
          onChange={(e) => setUrl(e.target.value)}
          disabled={Boolean(scanning)}
        />
        <button type="submit" className="button scan-button" disabled={Boolean(scanning) || !url.trim()}>
          {scanning ? "Scanning…" : "Scan"}
        </button>
      </form>
      <div className="scan-status" aria-live="polite">
        {scanning && (
          <>
            <p className="muted small">Scanning {scanning}... this takes about 15 seconds</p>
            <div className="scan-progress" aria-hidden="true" />
          </>
        )}
      </div>
      {error && <div className="banner" role="alert">{error}</div>}
    </section>
  );
}

export default function App() {
  const [data, setData] = useState(null);
  const [loadError, setLoadError] = useState(null);
  const [selected, setSelected] = useState(null);

  useEffect(() => {
    const load = (path) =>
      fetch(path).then((r) => {
        if (!r.ok) throw new Error(`${path} returned ${r.status}`);
        return r.json();
      });
    const bundled = `${import.meta.env.BASE_URL}findings.json`;
    (DEMO ? load(bundled) : load("/api/findings").catch(() => load(bundled)))
      .then(setData)
      .catch((e) => setLoadError(e.message));
  }, []);

  function select(name) {
    setSelected(name);
    window.scrollTo(0, 0);
  }

  function addScanned(entry) {
    setData((prev) => {
      const sites = [...(prev?.sites || [])];
      const i = sites.findIndex((s) => s.site === entry.site);
      if (i >= 0) sites[i] = entry;
      else sites.push(entry);
      return { ...(prev || {}), generated_at: new Date().toISOString(), sites };
    });
    setLoadError(null);
    select(entry.site);
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
        {!site && (DEMO ? <DemoScanBar /> : <ScanBar onScanned={addScanned} />)}
        {loadError && <div className="banner" role="alert">Couldn't load the scan results ({loadError}).</div>}
        {!data && !loadError && <p className="muted">Loading…</p>}
        {data && (site ? <SiteView site={site} onBack={() => select(null)} /> : <Overview data={data} onSelect={select} />)}
      </main>
      <footer className="footer muted small">
        IP geolocation by{" "}
        <a href="https://db-ip.com" target="_blank" rel="noreferrer noopener">DB-IP</a>
        {" "}(
        <a href="https://creativecommons.org/licenses/by/4.0/" target="_blank" rel="noreferrer noopener">CC BY 4.0</a>
        ).
        {DEMO && (
          <>
            {" "}Source on <a href={REPO_URL} target="_blank" rel="noreferrer noopener">GitHub</a>.
          </>
        )}
      </footer>
    </div>
  );
}
