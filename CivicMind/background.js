const DEFAULT_BACKEND_URL = "http://localhost:8000";

chrome.runtime.onInstalled.addListener(() => {
  chrome.storage.sync.get({ backendUrl: DEFAULT_BACKEND_URL }, (items) => {
    if (chrome.runtime.lastError) {
      console.warn("CivicMind failed to initialize storage:", chrome.runtime.lastError.message);
      return;
    }

    const backendUrl = normalizeBackendUrl(items.backendUrl || DEFAULT_BACKEND_URL);
    chrome.storage.sync.set({ backendUrl });
  });
});

chrome.action.onClicked.addListener((tab) => {
  if (!tab.id) {
    return;
  }

  chrome.tabs.sendMessage(tab.id, { action: "analyze_page" }, () => {
    if (chrome.runtime.lastError) {
      console.warn("CivicMind could not start on this page:", chrome.runtime.lastError.message);
    }
  });
});

chrome.runtime.onMessage.addListener((request, sender, sendResponse) => {
  if (request.action !== "analyze_article") {
    return false;
  }

  analyzeArticle(request.payload)
    .then((data) => sendResponse({ ok: true, data }))
    .catch((error) => sendResponse({ ok: false, error: error.message }));

  return true;
});

async function analyzeArticle(payload) {
  const backendUrl = await getBackendUrl();
  const response = await fetch(`${backendUrl}/api/analyze`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json"
    },
    body: JSON.stringify(payload)
  });

  let responseBody = null;
  try {
    responseBody = await response.json();
  } catch (error) {
    responseBody = null;
  }

  if (!response.ok) {
    const detail = responseBody && responseBody.detail ? responseBody.detail : `HTTP ${response.status}`;
    throw new Error(detail);
  }

  return responseBody;
}

function getBackendUrl() {
  return new Promise((resolve) => {
    chrome.storage.sync.get({ backendUrl: DEFAULT_BACKEND_URL }, (items) => {
      if (chrome.runtime.lastError) {
        resolve(DEFAULT_BACKEND_URL);
        return;
      }

      resolve(normalizeBackendUrl(items.backendUrl || DEFAULT_BACKEND_URL));
    });
  });
}

function normalizeBackendUrl(url) {
  return (url || DEFAULT_BACKEND_URL).trim().replace(/\/+$/, "");
}
