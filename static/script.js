// labels for known resolution buckets
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

document.addEventListener("DOMContentLoaded", () => {
  const formatRadios = document.querySelectorAll('input[name="format"]');
  const qualityGroup = document.getElementById("qualityGroup");
  const qualitySelect = document.getElementById("qualitySelect");
  const qualityIcon = document.getElementById("qualityIcon");
  const qualitySpinner = document.getElementById("qualitySpinner");
  const videoInfo = document.getElementById("videoInfo");
  const urlInput = document.getElementById("urlInput");

  // fallback options used when probing fails
  const defaultOptionsHtml = qualitySelect.innerHTML;

  let lastProbedUrl = null;
  let probeController = null;
  let debounceTimer = null;

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

  // swap the icon for a spinner while a probe is in flight
  function setProbing(probing) {
    qualityIcon.classList.toggle("hidden", probing);
    qualitySpinner.classList.toggle("hidden", !probing);
  }

  // state is "valid", "invalid" or "hidden"; the probe doubles as a link validity check
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
    videoInfo.querySelector(".title").textContent = text; // textContent avoids html injection
  }

  function populateOptions(heights) {
    const preserved = qualitySelect.value;
    let html = '<option value="best">Best Quality</option>';
    heights.forEach((h) => {
      html += `<option value="${h}">${labelForHeight(h)}</option>`;
    });
    qualitySelect.innerHTML = html;
    qualitySelect.disabled = false;
    // keep the previous choice if it still exists
    if ([...qualitySelect.options].some((o) => o.value === preserved)) {
      qualitySelect.value = preserved;
    }
  }

  async function probeFormats(url) {
    if (!url || url === lastProbedUrl) return;
    lastProbedUrl = url;

    // cancel any in-flight probe for an older url
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

      // a resolved title confirms the link is a real, reachable video
      setVideoInfo("valid", data.title || "Video found");

      if (data.heights && data.heights.length) {
        populateOptions(data.heights);
      } else {
        // extraction worked but exposed no heights, fall back to the static list
        qualitySelect.innerHTML = defaultOptionsHtml;
        qualitySelect.disabled = false;
      }
    } catch (err) {
      if (err.name === "AbortError") return;
      // probe failed: restore the static list and flag that we couldn't verify the link
      lastProbedUrl = null; // allow a retry on next change
      qualitySelect.innerHTML = defaultOptionsHtml;
      qualitySelect.disabled = false;
      setVideoInfo(
        "invalid",
        "Couldn't verify this link. it may be private, removed, or not a supported video.",
      );
    } finally {
      // only clear the spinner if a newer probe hasn't taken over
      if (probeController === controller) setProbing(false);
    }
  }

  // keep the quality selector hidden until mp4 is chosen and a url is entered
  function updateQualityVisibility() {
    const url = urlInput.value.trim();
    const show = isMp4Selected() && url !== "";
    qualityGroup.classList.toggle("hidden", !show);

    // reveal straight into the spinner for an unprobed url so it doesn't flash the default list
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

  // change fires on blur/enter; the debounced input handler catches pastes
  urlInput.addEventListener("change", () => {
    updateQualityVisibility();
    maybeProbe();
  });
  urlInput.addEventListener("input", () => {
    updateQualityVisibility();
    clearTimeout(debounceTimer);
    debounceTimer = setTimeout(maybeProbe, 700);
  });
});

// eslint-disable-next-line no-unused-vars
async function startDownload() {
  const urlInput = document.getElementById("urlInput");
  const url = urlInput.value.trim();
  const format = document.querySelector('input[name="format"]:checked').value;
  const quality = document.getElementById("qualitySelect").value;

  const downloadBtn = document.getElementById("downloadBtn");
  const btnText = document.getElementById("btnText");
  const btnIcon = document.getElementById("btnIcon");
  const btnSpinner = document.getElementById("btnSpinner");

  const statusContainer = document.getElementById("statusContainer");
  const progressBar = document.getElementById("progressBar");
  const statusMessage = document.getElementById("statusMessage");
  const percentage = document.getElementById("percentage");
  const errorContainer = document.getElementById("errorContainer");
  const errorMessage = document.getElementById("errorMessage");
  const noticeContainer = document.getElementById("noticeContainer");
  const noticeMessage = document.getElementById("noticeMessage");

  errorContainer.classList.add("hidden");
  noticeContainer.classList.add("hidden");
  statusContainer.classList.add("hidden");
  progressBar.style.width = "0%";

  if (!url) {
    showError("Please enter a valid video URL");
    return;
  }

  downloadBtn.disabled = true;
  btnText.textContent = "Processing...";
  btnIcon.style.display = "none";
  btnSpinner.style.display = "block";

  try {
    const response = await fetch("/api/download", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify({ url, format_type: format, quality: quality }),
    });

    const data = await response.json().catch(() => ({}));

    if (!response.ok) {
      // fastapi puts validation/refusal messages in detail
      showError(data.detail || `Request failed (status ${response.status})`);
      resetButton();
      return;
    }

    const taskId = data.task_id;

    // e.g. a single video pulled out of a playlist/mix
    if (data.notice) {
      showNotice(data.notice);
    }

    statusContainer.classList.remove("hidden");
    pollProgress(taskId);
  } catch (error) {
    showError("Failed to start download: " + error.message);
    resetButton();
  }

  function showError(msg) {
    errorContainer.classList.remove("hidden");
    errorMessage.textContent = msg;
  }

  function showNotice(msg) {
    noticeContainer.classList.remove("hidden");
    noticeMessage.textContent = msg;
  }

  function resetButton() {
    downloadBtn.disabled = false;
    btnText.textContent = "Download";
    btnIcon.style.display = "inline-block";
    btnSpinner.style.display = "none";
  }

  async function pollProgress(taskId) {
    const progressBox = document.getElementById("progressBox");
    const processingBox = document.getElementById("processingBox");

    const interval = setInterval(async () => {
      try {
        const res = await fetch(`/api/progress/${taskId}`);
        if (!res.ok) throw new Error("Progress check failed");

        const progressData = await res.json();

        if (progressData.status === "downloading") {
          progressBox.classList.remove("hidden");
          processingBox.classList.add("hidden");
          
          const percent = progressData.progress || 0;
          progressBar.style.width = percent + "%";
          percentage.textContent = Math.round(percent) + "%";
          statusMessage.textContent = `Downloading: ${progressData.filename || "..."}`;
        } else if (progressData.status === "processing") {
          // switch from progress bar to spinner
          progressBox.classList.add("hidden");
          processingBox.classList.remove("hidden");
        } else if (progressData.status === "finished") {
          processingBox.classList.add("hidden");
          clearInterval(interval);

          // trigger the file download via a temporary anchor
          const link = document.createElement('a');
          link.href = `/api/download_file/${taskId}`;
          link.download = ''; 
          document.body.appendChild(link);
          link.click();
          document.body.removeChild(link);
          
          resetButton();
          statusContainer.classList.add("hidden");
        } else if (progressData.status === "error") {
          clearInterval(interval);
          resetButton();
          statusContainer.classList.add("hidden");
          showError(progressData.error || "Unknown error occurred");
        }
      } catch (err) {
        console.error(err);
      }
    }, 1000);
  }
}

// expose for the onclick handler
window.startDownload = startDownload;
