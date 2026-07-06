function setStatus(text) {
  document.getElementById("status").textContent = text;
}

async function capture(captureType) {
  setStatus("Capturing…");
  const resp = await chrome.runtime.sendMessage({
    type: "maya.captureActiveTab",
    captureType,
  });
  if (!resp?.ok) {
    setStatus(resp?.error || "Capture failed");
    return;
  }
  const m = resp.manifest;
  setStatus(
    m.duplicate
      ? `Duplicate — ${m.capture_id}`
      : `Saved ${m.capture_id} (${m.stored_assets.length} assets)`
  );
}

document.getElementById("save").addEventListener("click", () => capture("article"));
document.getElementById("research").addEventListener("click", () => capture("paper"));
document.getElementById("capture").addEventListener("click", () => capture("generic"));
