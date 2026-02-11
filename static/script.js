async function startDownload() {
  const urlInput = document.getElementById("urlInput");
  const url = urlInput.value.trim();
  const format = document.querySelector('input[name="format"]:checked').value;

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

  // Reset UI
  errorContainer.classList.add("hidden");
  statusContainer.classList.add("hidden");
  progressBar.style.width = "0%";

  if (!url) {
    showError("Please enter a valid YouTube URL");
    return;
  }

  // Set Loading State
  downloadBtn.disabled = true;
  btnText.textContent = "Processing...";
  btnIcon.style.display = "none";
  btnSpinner.style.display = "block";

  try {
    // Start Download
    const response = await fetch("/api/download", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify({ url, format_type: format }),
    });

    if (!response.ok) {
      throw new Error(`HTTP error! status: ${response.status}`);
    }

    const data = await response.json();
    const taskId = data.task_id;

    // Start Polling
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

  function resetButton() {
    downloadBtn.disabled = false;
    btnText.textContent = "Download";
    btnIcon.style.display = "inline-block";
    btnSpinner.style.display = "none";
  }

  async function pollProgress(taskId) {
    const interval = setInterval(async () => {
      try {
        const res = await fetch(`/api/progress/${taskId}`);
        if (!res.ok) throw new Error("Progress check failed");

        const progressData = await res.json();

        // Update UI
        if (progressData.status === "downloading") {
          const percent = progressData.progress || 0;
          progressBar.style.width = percent + "%";
          percentage.textContent = Math.round(percent) + "%";
          statusMessage.textContent = `Downloading: ${progressData.filename || "..."}`;
        } else if (progressData.status === "finished") {
          progressBar.style.width = "100%";
          percentage.textContent = "100%";
          statusMessage.textContent = "Download Complete! Starting file download...";
          clearInterval(interval);
          
          // Trigger file download using a temporary anchor tag
          const link = document.createElement('a');
          link.href = `/api/download_file/${taskId}`;
          link.download = ''; // Browser will infer filename from Content-Disposition
          document.body.appendChild(link);
          link.click();
          document.body.removeChild(link);
          
          resetButton();
          // Removed alert to make it smoother
        } else if (progressData.status === "error") {
          clearInterval(interval);
          resetButton();
          showError(progressData.error || "Unknown error occurred");
        }
      } catch (err) {
        console.error(err);
        // Don't stop polling immediately on one error, but maybe warn?
      }
    }, 1000);
  }
}
