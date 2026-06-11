const HEIGHT_LABELS = {
  4320: "8K (4320p)",
  2160: "4K (2160p)",
  1440: "2K (1440p)",
  1080: "1080p",
  720: "720p",
  480: "480p",
  360: "360p",
  240: "240p",
  144: "144p",
};

function labelForHeight(h) {
  return HEIGHT_LABELS[h] || `${h}p`;
}

const TASK_STORAGE_KEY = "ytdl-active-task";
const MAX_POLL_FAILURES = 15;

document.addEventListener("DOMContentLoaded", () => {
  const formatRadios = document.querySelectorAll('input[name="format"]');
  const qualityGroup = document.getElementById("qualityGroup");
  const qualitySelect = document.getElementById("qualitySelect");
  const qualityIcon = document.getElementById("qualityIcon");
  const qualitySpinner = document.getElementById("qualitySpinner");
  const videoInfo = document.getElementById("videoInfo");
  const urlInput = document.getElementById("urlInput");

  const downloadBtn = document.getElementById("downloadBtn");
  const btnText = document.getElementById("btnText");
  const btnIcon = document.getElementById("btnIcon");
  const btnFill = document.getElementById("btnFill");
  const errorContainer = document.getElementById("errorContainer");
  const errorMessage = document.getElementById("errorMessage");
  const noticeContainer = document.getElementById("noticeContainer");
  const noticeMessage = document.getElementById("noticeMessage");
  const cancelRow = document.getElementById("cancelRow");
  const cancelBtn = document.getElementById("cancelBtn");

  const defaultOptionsHtml = qualitySelect.innerHTML;

  let lastProbedUrl = null;
  let probeController = null;
  let debounceTimer = null;
  let currentTaskId = null;
  let pollInterval = null;

  function isMp4Selected() {
    const checked = document.querySelector('input[name="format"]:checked');
    return checked && checked.value === "mp4";
  }

  function setSelectState(disabled, placeholder) {
    qualitySelect.disabled = disabled;
    if (placeholder) {
      qualitySelect.innerHTML = `<option value="best">${placeholder}</option>`;
    }
  }

  function setProbing(probing) {
    qualityIcon.classList.toggle("hidden", probing);
    qualitySpinner.classList.toggle("hidden", !probing);
  }

  function setVideoInfo(state, text) {
    if (!videoInfo) return;
    if (state === "hidden") {
      videoInfo.className = "video-info hidden";
      videoInfo.textContent = "";
      return;
    }
    const icon = state === "valid" ? "fa-circle-check" : "fa-circle-exclamation";
    videoInfo.className = `video-info ${state}`;
    videoInfo.innerHTML = `<i class="fas ${icon}"></i><span class="title"></span>`;
    videoInfo.querySelector(".title").textContent = text;
  }

  function populateOptions(heights) {
    const preserved = qualitySelect.value;
    let html = '<option value="best">Best Quality</option>';
    heights.forEach((h) => {
      html += `<option value="${h}">${labelForHeight(h)}</option>`;
    });
    qualitySelect.innerHTML = html;
    qualitySelect.disabled = false;
    if ([...qualitySelect.options].some((o) => o.value === preserved)) {
      qualitySelect.value = preserved;
    }
  }

  async function probeFormats(url) {
    if (!url || url === lastProbedUrl) return;
    lastProbedUrl = url;

    if (probeController) probeController.abort();
    const controller = new AbortController();
    probeController = controller;

    setSelectState(true, "Loading available qualities…");
    setProbing(true);
    setVideoInfo("hidden");

    try {
      const res = await fetch("/api/formats", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ url }),
        signal: controller.signal,
      });

      if (!res.ok) throw new Error("probe failed");
      const data = await res.json();

      setVideoInfo("valid", data.title || "Video found");

      if (data.heights && data.heights.length) {
        populateOptions(data.heights);
      } else {
        qualitySelect.innerHTML = defaultOptionsHtml;
        qualitySelect.disabled = false;
      }
    } catch (err) {
      if (err.name === "AbortError") return;
      lastProbedUrl = null;
      qualitySelect.innerHTML = defaultOptionsHtml;
      qualitySelect.disabled = false;
      setVideoInfo(
        "invalid",
        "Couldn't verify this link. it may be private, removed, or not a supported video.",
      );
    } finally {
      if (probeController === controller) setProbing(false);
    }
  }

  function updateQualityVisibility() {
    const url = urlInput.value.trim();
    const show = isMp4Selected() && url !== "";
    qualityGroup.classList.toggle("hidden", !show);

    if (show && url !== lastProbedUrl) {
      setSelectState(true, "Loading available qualities…");
      setProbing(true);
      setVideoInfo("hidden");
    }
  }

  function maybeProbe() {
    if (!isMp4Selected()) return;
    const url = urlInput.value.trim();
    if (!url) return;
    probeFormats(url);
  }

  formatRadios.forEach((radio) => {
    radio.addEventListener("change", () => {
      updateQualityVisibility();
      maybeProbe();
    });
  });

  urlInput.addEventListener("change", () => {
    updateQualityVisibility();
    maybeProbe();
  });
  urlInput.addEventListener("input", () => {
    updateQualityVisibility();
    clearTimeout(debounceTimer);
    debounceTimer = setTimeout(maybeProbe, 700);
  });

  // download flow

  function showError(msg) {
    errorContainer.classList.remove("hidden");
    errorMessage.textContent = msg;
  }

  function showNotice(msg) {
    noticeContainer.classList.remove("hidden");
    noticeMessage.textContent = msg;
  }

  function setBusy(text) {
    downloadBtn.disabled = true;
    btnText.textContent = text || "Starting…";
    btnIcon.style.display = "none";
    btnFill.classList.add("indeterminate");
  }

  function resetButton() {
    currentTaskId = null;
    if (pollInterval) {
      clearInterval(pollInterval);
      pollInterval = null;
    }
    downloadBtn.disabled = false;
    btnText.textContent = "Download";
    btnIcon.className = "fas fa-arrow-down-long";
    btnIcon.style.display = "inline-block";
    btnFill.classList.remove("indeterminate");
    btnFill.style.width = "0%";
  }

  function detailToMessage(detail, fallback) {
    if (typeof detail === "string") return detail;
    if (Array.isArray(detail)) {
      const msgs = detail.map((d) => d && d.msg).filter(Boolean);
      if (msgs.length) return msgs.join("; ");
    }
    return fallback;
  }

  function showIndeterminate(buttonText) {
    btnText.textContent = buttonText;
    btnFill.classList.add("indeterminate");
  }

  function triggerFileDownload(taskId) {
    const link = document.createElement("a");
    link.href = `/api/download_file/${taskId}`;
    link.download = "";
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
  }

  async function cancelDownload(taskId) {
    try {
      const res = await fetch(`/api/cancel/${taskId}`, { method: "POST" });
      if (!res.ok) {
        const data = await res.json().catch(() => ({}));
        showError(data.detail || "Failed to cancel download");
        return;
      }
    } catch (err) {
      showError("Failed to cancel: " + err.message);
    }
  }

  function finishTask() {
    sessionStorage.removeItem(TASK_STORAGE_KEY);
    resetButton();
  }

  function showCancelRow(cancelling) {
    cancelRow.classList.remove("hidden");
    cancelBtn.disabled = !!cancelling;
    cancelBtn.innerHTML = cancelling
      ? '<i class="fas fa-spinner fa-spin"></i> Cancelling…'
      : '<i class="fas fa-xmark"></i> Cancel';
  }

  function pollProgress(taskId) {
    let failures = 0;

    pollInterval = setInterval(async () => {
      try {
        const res = await fetch(`/api/progress/${taskId}`);
        if (!res.ok) throw new Error(`Progress check failed (${res.status})`);
        failures = 0;

        const progressData = await res.json();

        if (progressData.status === "queued" || progressData.status === "starting") {
          setBusy("Starting…");
          showCancelRow(false);
        } else if (progressData.status === "downloading") {
          const percent = Math.round(progressData.progress || 0);
          downloadBtn.disabled = true;
          btnIcon.style.display = "none";
          btnText.textContent = `Downloading ${percent}%`;
          btnFill.classList.remove("indeterminate");
          btnFill.style.width = percent + "%";
          showCancelRow(false);
        } else if (progressData.status === "cancelling") {
          showCancelRow(true);
        } else if (progressData.status === "cancelled") {
          clearInterval(pollInterval);
          pollInterval = null;
          finishTask();
          showNotice("Download was cancelled.");
        } else if (progressData.status === "processing") {
          setBusy("Converting…");
          showCancelRow(false);
        } else if (progressData.status === "finished") {
          clearInterval(pollInterval);
          pollInterval = null;
          triggerFileDownload(taskId);
          finishTask();
        } else if (progressData.status === "error") {
          clearInterval(pollInterval);
          pollInterval = null;
          finishTask();
          showError(progressData.error || "Unknown error occurred");
        }
      } catch (err) {
        failures += 1;
        if (failures >= MAX_POLL_FAILURES) {
          clearInterval(pollInterval);
          pollInterval = null;
          console.error(err);
          finishTask();
          showError("Lost connection to the server. The download may have been interrupted.");
        }
      }
    }, 1000);
  }

  async function startDownload() {
    const url = urlInput.value.trim();
    const format = document.querySelector('input[name="format"]:checked').value;
    const quality = qualitySelect.value;

    errorContainer.classList.add("hidden");
    noticeContainer.classList.add("hidden");

    if (!url) {
      showError("Please enter a valid video URL");
      return;
    }

    setBusy();

    try {
      const response = await fetch("/api/download", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify({ url, format_type: format, quality: quality }),
      });

      const data = await response.json().catch(() => ({}));

      if (!response.ok || !data.task_id) {
        showError(detailToMessage(data.detail, `Request failed (status ${response.status})`));
        resetButton();
        return;
      }

      const taskId = data.task_id;
      currentTaskId = taskId;
      sessionStorage.setItem(TASK_STORAGE_KEY, taskId);

      if (data.notice) {
        showNotice(data.notice);
      }

      showCancelRow(false);
      pollProgress(taskId);
    } catch (error) {
      showError("Failed to start download: " + error.message);
      resetButton();
    }
  }

  downloadBtn.addEventListener("click", startDownload);
  cancelBtn.addEventListener("click", () => {
    if (currentTaskId) cancelDownload(currentTaskId);
  });

  (async () => {
    const storedId = sessionStorage.getItem(TASK_STORAGE_KEY);
    if (!storedId) return;

    try {
      const res = await fetch(`/api/progress/${storedId}`);
      if (!res.ok) {
        sessionStorage.removeItem(TASK_STORAGE_KEY);
        return;
      }
      const data = await res.json();

      if (data.status === "finished") {
        triggerFileDownload(storedId);
        finishTask();
      } else if (data.status === "error" || data.status === "cancelled") {
        finishTask();
        if (data.status === "error") {
          showError(data.error || "Unknown error occurred");
        }
      } else {
        currentTaskId = storedId;
        setBusy("Reconnecting…");
        showCancelRow(false);
        pollProgress(storedId);
      }
    } catch {}
  })();
});
