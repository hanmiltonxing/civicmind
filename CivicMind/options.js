const DEFAULT_BACKEND_URL = "http://localhost:8000";

document.addEventListener("DOMContentLoaded", () => {
  const backendInput = document.getElementById("backend-url");
  const status = document.getElementById("status");
  const saveButton = document.getElementById("save-button");
  const resetButton = document.getElementById("reset-button");

  chrome.storage.sync.get({ backendUrl: DEFAULT_BACKEND_URL }, (items) => {
    backendInput.value = normalizeBackendUrl(items.backendUrl || DEFAULT_BACKEND_URL);
  });

  saveButton.addEventListener("click", () => {
    const backendUrl = normalizeBackendUrl(backendInput.value);
    if (!isValidBackendUrl(backendUrl)) {
      status.textContent = "Enter a valid http:// or https:// URL.";
      status.style.color = "#b3261e";
      return;
    }

    chrome.storage.sync.set({ backendUrl }, () => {
      if (chrome.runtime.lastError) {
        status.textContent = `Save failed: ${chrome.runtime.lastError.message}`;
        status.style.color = "#b3261e";
        return;
      }

      backendInput.value = backendUrl;
      status.textContent = "Backend URL saved.";
      status.style.color = "#1a7f37";
    });
  });

  resetButton.addEventListener("click", () => {
    chrome.storage.sync.set({ backendUrl: DEFAULT_BACKEND_URL }, () => {
      if (chrome.runtime.lastError) {
        status.textContent = `Reset failed: ${chrome.runtime.lastError.message}`;
        status.style.color = "#b3261e";
        return;
      }

      backendInput.value = DEFAULT_BACKEND_URL;
      status.textContent = "Reset to the local default URL.";
      status.style.color = "#1a7f37";
    });
  });
});

function normalizeBackendUrl(value) {
  return (value || DEFAULT_BACKEND_URL).trim().replace(/\/+$/, "");
}

function isValidBackendUrl(value) {
  return /^https?:\/\/.+/i.test(value);
}
