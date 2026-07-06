const fields = ["gatewayUrl", "captureToken", "captureType"];

document.addEventListener("DOMContentLoaded", async () => {
  const stored = await chrome.storage.sync.get({
    gatewayUrl: "http://localhost:8090",
    captureToken: "",
    captureType: "article",
  });
  for (const id of fields) {
    document.getElementById(id).value = stored[id] || "";
  }
});

document.getElementById("save").addEventListener("click", async () => {
  const data = {};
  for (const id of fields) {
    data[id] = document.getElementById(id).value.trim();
  }
  await chrome.storage.sync.set(data);
  document.getElementById("saved").textContent = "Saved.";
});
