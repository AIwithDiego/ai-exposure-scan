// FIXTURE: planted key leak. This key is FAKE and does not work. It exists so the scanner has something to find.
const OPENAI_KEY = "sk-proj-DEMO0000FAKE0000NOTAREALKEY0000cafe";

document.getElementById("suggest").addEventListener("click", async () => {
  // Never actually called by the scanner (we never click anything).
  const res = await fetch("https://api.openai.com/v1/chat/completions", {
    method: "POST",
    headers: { "Authorization": "Bearer " + OPENAI_KEY, "Content-Type": "application/json" },
    body: JSON.stringify({ model: "gpt-4o-mini", messages: [{ role: "user", content: "Suggest a café treat" }] })
  });
  const data = await res.json();
  document.getElementById("suggestion").textContent = data.choices[0].message.content;
});
