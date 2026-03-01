(() => {
    "use strict";

    // --- State ---
    let sessionId = null;
    let mediaType = null;
    let mediaWidth = 0;
    let mediaHeight = 0;
    let numSlices = 3;
    let sliceResults = null;

    // --- DOM refs ---
    const dropZone = document.getElementById("drop-zone");
    const fileInput = document.getElementById("file-input");
    const uploadProgress = document.getElementById("upload-progress");
    const progressFill = document.getElementById("upload-progress-fill");
    const progressText = document.getElementById("upload-progress-text");

    const sourceSection = document.getElementById("source-section");
    const sourceMediaWrap = document.getElementById("source-media-wrap");
    const guideLines = document.getElementById("guide-lines");
    const sourceDimensions = document.getElementById("source-dimensions");
    const sourceTypeBadge = document.getElementById("source-type-badge");

    const controlsSection = document.getElementById("controls-section");
    const sliceButtons = document.getElementById("slice-buttons");
    const sliceRange = document.getElementById("slice-range");
    const sliceCountLabel = document.getElementById("slice-count-label");
    const sliceBtn = document.getElementById("slice-btn");
    const resetBtn = document.getElementById("reset-btn");
    const sliceStatus = document.getElementById("slice-status");

    const resultsSection = document.getElementById("results-section");
    const resultsGrid = document.getElementById("results-grid");
    const downloadAllBtn = document.getElementById("download-all-btn");

    // --- Upload handling ---

    dropZone.addEventListener("click", () => fileInput.click());

    dropZone.addEventListener("dragover", (e) => {
        e.preventDefault();
        dropZone.classList.add("drop-zone--active");
    });

    dropZone.addEventListener("dragleave", () => {
        dropZone.classList.remove("drop-zone--active");
    });

    dropZone.addEventListener("drop", (e) => {
        e.preventDefault();
        dropZone.classList.remove("drop-zone--active");
        if (e.dataTransfer.files.length > 0) {
            uploadFile(e.dataTransfer.files[0]);
        }
    });

    fileInput.addEventListener("change", () => {
        if (fileInput.files.length > 0) {
            uploadFile(fileInput.files[0]);
        }
    });

    function uploadFile(file) {
        resetUI();
        const formData = new FormData();
        formData.append("file", file);

        uploadProgress.hidden = false;
        progressFill.style.width = "0%";
        progressText.textContent = "0%";

        const xhr = new XMLHttpRequest();
        xhr.open("POST", "/api/upload");

        xhr.upload.addEventListener("progress", (e) => {
            if (e.lengthComputable) {
                const pct = Math.round((e.loaded / e.total) * 100);
                progressFill.style.width = pct + "%";
                progressText.textContent = pct + "%";
            }
        });

        xhr.addEventListener("load", () => {
            uploadProgress.hidden = true;
            if (xhr.status !== 200) {
                let msg = "Upload failed";
                try { msg = JSON.parse(xhr.responseText).error; } catch {}
                showError(msg);
                return;
            }
            const data = JSON.parse(xhr.responseText);
            handleUploadSuccess(data);
        });

        xhr.addEventListener("error", () => {
            uploadProgress.hidden = true;
            showError("Network error during upload.");
        });

        xhr.send(formData);
    }

    function handleUploadSuccess(data) {
        sessionId = data.session_id;
        mediaType = data.type;
        mediaWidth = data.width;
        mediaHeight = data.height;

        // If video but ffmpeg is missing, show error and don't try to preview
        if (mediaType === "video" && data.ffmpeg_available === false) {
            sourceSection.hidden = false;
            sourceMediaWrap.innerHTML = "";
            sourceDimensions.textContent = "Unknown (ffmpeg not installed)";
            sourceTypeBadge.textContent = mediaType;

            const notice = document.createElement("div");
            notice.style.cssText = "padding:2rem;text-align:center;color:var(--text-secondary,#888);";
            notice.textContent = "Video preview unavailable without ffmpeg.";
            sourceMediaWrap.appendChild(notice);

            controlsSection.hidden = false;
            showStatus(
                "ffmpeg is not installed on the server. Video slicing will not work. " +
                'Install ffmpeg to enable this feature: <a href="https://ffmpeg.org/download.html" target="_blank">ffmpeg.org/download</a>',
                "error"
            );
            sliceBtn.disabled = true;
            return;
        }

        // Show source preview
        sourceSection.hidden = false;
        sourceMediaWrap.innerHTML = "";

        const src = `/api/source/${sessionId}/${data.filename}`;
        if (mediaType === "image") {
            const img = document.createElement("img");
            img.src = src;
            img.alt = "Source image";
            sourceMediaWrap.appendChild(img);
        } else {
            const video = document.createElement("video");
            video.src = src;
            video.controls = true;
            video.muted = true;
            sourceMediaWrap.appendChild(video);
        }

        sourceDimensions.textContent = `${mediaWidth} x ${mediaHeight} px`;
        sourceTypeBadge.textContent = mediaType;

        // Set suggested slices
        numSlices = data.suggested_slices;
        if (numSlices > 10) {
            sliceRange.value = numSlices;
        }

        // Show controls
        controlsSection.hidden = false;
        buildSliceButtons();
        syncSliceUI();
        updateGuideLines();
    }

    // --- Slice count controls ---

    function buildSliceButtons() {
        sliceButtons.innerHTML = "";
        for (let i = 2; i <= 10; i++) {
            const btn = document.createElement("button");
            btn.className = "slice-num-btn";
            btn.textContent = i;
            btn.dataset.count = i;
            btn.addEventListener("click", () => {
                numSlices = i;
                syncSliceUI();
                updateGuideLines();
            });
            sliceButtons.appendChild(btn);
        }
    }

    function syncSliceUI() {
        sliceRange.value = numSlices;
        sliceCountLabel.textContent = numSlices;

        document.querySelectorAll(".slice-num-btn").forEach((btn) => {
            btn.classList.toggle("active", parseInt(btn.dataset.count) === numSlices);
        });
    }

    sliceRange.addEventListener("input", () => {
        numSlices = parseInt(sliceRange.value);
        syncSliceUI();
        updateGuideLines();
    });

    // --- Guide lines ---

    function updateGuideLines() {
        guideLines.innerHTML = "";
        for (let i = 1; i < numSlices; i++) {
            const pct = (i / numSlices) * 100;
            const line = document.createElement("div");
            line.className = "guide-line";
            line.style.left = pct + "%";
            guideLines.appendChild(line);
        }
    }

    // --- Slicing ---

    sliceBtn.addEventListener("click", () => {
        if (!sessionId) return;

        sliceBtn.disabled = true;
        resultsSection.hidden = true;
        showStatus('<span class="spinner"></span> Slicing your media...', "loading");

        fetch("/api/slice", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ session_id: sessionId, num_slices: numSlices }),
        })
            .then((res) => res.json().then((data) => ({ ok: res.ok, data })))
            .then(({ ok, data }) => {
                sliceBtn.disabled = false;
                if (!ok) {
                    showStatus(data.error || "Slicing failed", "error");
                    return;
                }
                hideStatus();
                sliceResults = data;
                showResults(data);
            })
            .catch(() => {
                sliceBtn.disabled = false;
                showStatus("Network error during slicing.", "error");
            });
    });

    function showResults(data) {
        resultsSection.hidden = false;
        resultsGrid.innerHTML = "";

        data.slices.forEach((filename, idx) => {
            const card = document.createElement("div");
            card.className = "slide-card";

            const previewUrl = `/api/preview/${data.session_id}/${filename}`;
            const downloadUrl = `/api/download/${data.session_id}/${filename}`;

            let preview;
            if (data.type === "image") {
                preview = document.createElement("img");
                preview.src = previewUrl;
                preview.alt = `Slide ${idx + 1}`;
                preview.className = "slide-card__preview";
            } else {
                preview = document.createElement("video");
                preview.src = previewUrl;
                preview.className = "slide-card__preview";
                preview.muted = true;
                preview.loop = true;
                preview.addEventListener("mouseenter", () => preview.play());
                preview.addEventListener("mouseleave", () => {
                    preview.pause();
                    preview.currentTime = 0;
                });
            }

            const info = document.createElement("div");
            info.className = "slide-card__info";

            const label = document.createElement("span");
            label.className = "slide-card__label";
            label.textContent = String(idx + 1).padStart(2, '0');

            const dlBtn = document.createElement("a");
            dlBtn.href = downloadUrl;
            dlBtn.className = "btn btn--secondary btn--small";
            dlBtn.textContent = "\u2193";
            dlBtn.download = filename;

            info.appendChild(label);
            info.appendChild(dlBtn);
            card.appendChild(preview);
            card.appendChild(info);
            resultsGrid.appendChild(card);
        });

        resultsSection.scrollIntoView({ behavior: "smooth", block: "start" });
    }

    // --- Download all ---

    downloadAllBtn.addEventListener("click", () => {
        if (!sliceResults) return;
        window.location.href = `/api/download-zip/${sliceResults.session_id}`;
    });

    // --- Reset ---

    resetBtn.addEventListener("click", resetUI);

    function resetUI() {
        sessionId = null;
        mediaType = null;
        sliceResults = null;
        numSlices = 3;

        sourceSection.hidden = true;
        controlsSection.hidden = true;
        resultsSection.hidden = true;
        uploadProgress.hidden = true;
        hideStatus();
        sliceBtn.disabled = false;
        fileInput.value = "";

        sourceMediaWrap.innerHTML = "";
        guideLines.innerHTML = "";
        resultsGrid.innerHTML = "";
    }

    // --- Status helpers ---

    function showStatus(msg, type) {
        sliceStatus.hidden = false;
        sliceStatus.innerHTML = msg;
        sliceStatus.className = `status-message status-message--${type}`;
    }

    function hideStatus() {
        sliceStatus.hidden = true;
    }

    function showError(msg) {
        showStatus(msg, "error");
        controlsSection.hidden = false;
    }
})();
