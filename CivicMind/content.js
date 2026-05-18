chrome.runtime.onMessage.addListener((request, sender, sendResponse) => {
  if (request.action === "analyze_page") {
    handleAnalyzePage();
  }
});

function handleAnalyzePage() {
  let sidebar = document.getElementById("clearlens-sidebar");

  if (sidebar) {
    sidebar.remove();
    return;
  }

  const payload = buildAnalyzePayload();
  sidebar = createSidebar();

  if (!payload.text) {
    renderError("Not enough article text was captured. Open a full article page and try again.");
    return;
  }

  chrome.runtime.sendMessage(
    {
      action: "analyze_article",
      payload
    },
    (response) => {
      if (chrome.runtime.lastError) {
        renderError(`Extension messaging failed: ${chrome.runtime.lastError.message}`);
        return;
      }

      if (!response || !response.ok) {
        renderError(response?.error || "Analysis failed. Check the backend service and Vertex AI configuration.");
        return;
      }

      renderAnalysis(response.data);
    }
  );
}

function createSidebar() {
  const sidebar = document.createElement("div");
  sidebar.id = "clearlens-sidebar";
  sidebar.innerHTML = `
    <div class="cl-header">
      <h2>CivicMind Reading This Page...</h2>
      <button id="cl-close" type="button" aria-label="Close sidebar">✖</button>
    </div>
    <div id="cl-content" class="cl-content">
      <p class="cl-loading">Reviewing the article and mapping possible framing and influence signals...</p>
    </div>
  `;
  const mountNode = document.body || document.documentElement;
  mountNode.appendChild(sidebar);

  sidebar.querySelector("#cl-close").addEventListener("click", () => {
    sidebar.remove();
  });

  return sidebar;
}

function renderAnalysis(data) {
  const contentDiv = document.getElementById("cl-content");
  const headerTitle = document.querySelector(".cl-header h2");
  if (!contentDiv || !headerTitle) {
    return;
  }

  headerTitle.innerText = "CivicMind Reflection";

  const summary = data.summary && typeof data.summary === "object" ? data.summary : {};
  const missingContext = Array.isArray(data.missing_context) ? data.missing_context : [];
  const parallelReporting = Array.isArray(data.parallel_reporting) ? data.parallel_reporting : [];
  const hasSummary = Boolean(summary.stance || summary.objectivity || summary.summary);

  let html = `
    <h3>🧭 Partisan Framing</h3>
    <p class="cl-section-copy">This section identifies whether the article uses an extreme Democratic-aligned or Republican-aligned framing and summarizes the core narrative in neutral language.</p>
    ${
      hasSummary
        ? `
      <div class="cl-summary-card">
        <div class="cl-summary-meta">
          <span class="cl-badge">Party Framing: ${escapeHtml(summary.stance || "Unclear")}</span>
          <span class="cl-badge">Polarization Read: ${escapeHtml(summary.objectivity || "Not enough evidence")}</span>
        </div>
        <p class="cl-summary-text">${escapeHtml(summary.summary || "The model did not return a short overview.")}</p>
      </div>
    `
        : `
      <div class="cl-summary-card">
        <p class="cl-summary-text">The model could not determine whether the captured text mainly reflected extreme Democratic-aligned or Republican-aligned framing.</p>
      </div>
    `
    }

    <h3>🔍 Missing Context</h3>
    <p class="cl-section-copy">This section highlights missing facts, assumptions, or overlooked concerns that supporters of the opposing U.S. party would need in order to understand the issue more fairly.</p>
    <ul class="cl-list">
      ${
        missingContext.length
          ? missingContext.map((item) => `<li>${escapeHtml(item)}</li>`).join("")
          : `<li>The model did not identify specific cross-party context gaps here. Compare this story with other reporting and look for evidence or concerns the opposing party would emphasize.</li>`
      }
    </ul>

    <h3>🌐 Cross-Party Perspective</h3>
    <p class="cl-section-copy">This section suggests how the same issue might be framed from the opposing major-party perspective, helping Democratic and Republican readers better understand each other.</p>
    <div class="cl-cards">
      ${
        parallelReporting.length
          ? parallelReporting.map((item) => `
        <div class="cl-card">
          <span class="cl-stance">${escapeHtml(item.stance || "Opposing party perspective")}</span>
          <h4>${escapeHtml(item.simulated_headline || "No headline provided")}</h4>
          <p><small>${escapeHtml(item.core_summary || "The model did not return a bridge-building perspective summary.")}</small></p>
        </div>
      `).join("")
          : `<div class="cl-card"><p><small>This section is meant to show how the opposing U.S. party perspective might frame the same issue so readers can compare narratives more fairly. The model did not return enough content.</small></p></div>`
      }
    </div>
  `;

  contentDiv.innerHTML = html;
}

function renderError(message) {
  const contentDiv = document.getElementById("cl-content");
  const headerTitle = document.querySelector(".cl-header h2");
  if (!contentDiv || !headerTitle) {
    return;
  }

  headerTitle.innerText = "CivicMind Could Not Finish";
  contentDiv.innerHTML = `
    <p class="cl-error">${escapeHtml(message)}</p>
    <p class="cl-help">
      Make sure the backend service is running and that the active model provider configuration is correct.
    </p>
  `;
}

function buildAnalyzePayload() {
  return {
    title: normalizeText(document.title),
    url: window.location.href,
    language: document.documentElement.lang || "unknown",
    text: extractArticleText()
  };
}

function extractArticleText() {
  const selectors = [
    "article",
    "main article",
    "main",
    "[role='main']",
    ".article-body",
    ".story-body",
    ".post-content",
    ".entry-content",
    ".article-content",
    ".content__article-body"
  ];

  for (const selector of selectors) {
    const element = document.querySelector(selector);
    const text = collectReadableText(element);
    if (text.length >= 600) {
      return text.slice(0, 12000);
    }
  }

  return collectReadableText(document.body || document.documentElement).slice(0, 12000);
}

function collectReadableText(root) {
  if (!root) {
    return "";
  }

  const blocks = Array.from(root.querySelectorAll("h1, h2, h3, p, li, blockquote"));
  const text = blocks
    .filter((element) => isVisible(element))
    .map((element) => normalizeText(element.innerText))
    .filter((value) => value.length >= 40 && !value.includes("CivicMind"))
    .join("\n\n");

  if (text.length >= 400) {
    return text;
  }

  return normalizeText(root.innerText).replace(/CivicMind[\s\S]*$/, "").trim();
}

function isVisible(element) {
  const styles = window.getComputedStyle(element);
  return styles.display !== "none" && styles.visibility !== "hidden";
}

function normalizeText(value) {
  return (value || "").replace(/\s+/g, " ").trim();
}

function escapeHtml(value) {
  return String(value || "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#39;");
}
