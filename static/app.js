(() => {
  "use strict";

  const ALLOWED_TYPES = ["image/jpeg", "image/png", "image/webp"];
  let maxBytes = 10 * 1024 * 1024;

  const $ = (id) => document.getElementById(id);
  const els = {
    modelLine: $("model-line"),
    maxMb: $("max-mb"),
    fileInput: $("file-input"),
    previewWrap: $("preview-wrap"),
    preview: $("preview"),
    fileName: $("file-name"),
    analyze: $("analyze-btn"),
    clear: $("clear-btn"),
    loading: $("loading"),
    error: $("error-box"),
    results: $("results"),
    badge: $("status-badge"),
    message: $("result-message"),
    topList: $("top-list"),
    nutritionWrap: $("nutrition-wrap"),
    nutritionBody: $("nutrition-body"),
    fbYes: $("fb-yes"),
    fbNo: $("fb-no"),
    fbCorrection: $("fb-correction"),
    fbLabel: $("fb-label"),
    fbSend: $("fb-send"),
    fbThanks: $("fb-thanks"),
    calNotice: $("cal-notice"),
    calBody: $("cal-body"),
  };

  let selectedFile = null;
  let previewUrl = null;
  let lastPrediction = null;

  const formatSize = (bytes) =>
    bytes < 1024 * 1024 ? `${(bytes / 1024).toFixed(1)} KB` : `${(bytes / 1024 / 1024).toFixed(2)} MB`;

  const showError = (message) => {
    els.error.textContent = message || "";
    els.error.hidden = !message;
  };

  const validateFile = (file) => {
    if (!file) return "파일을 선택하세요.";
    if (file.size === 0) return "빈 파일입니다. 다른 사진을 선택하세요.";
    if (!ALLOWED_TYPES.includes(file.type)) return "JPEG, PNG, WEBP 사진만 선택할 수 있습니다.";
    if (file.size > maxBytes) return `파일이 너무 큽니다. ${Math.round(maxBytes / 1024 / 1024)}MB 이하만 가능합니다.`;
    return null;
  };

  const clearResults = () => {
    lastPrediction = null;
    els.results.hidden = true;
    els.topList.replaceChildren();
    els.nutritionBody.replaceChildren();
    els.nutritionWrap.hidden = true;
    els.fbCorrection.hidden = true;
    els.fbThanks.hidden = true;
    els.fbYes.disabled = false;
    els.fbNo.disabled = false;
    els.fbLabel.value = "";
  };

  const updateButtons = () => {
    els.analyze.disabled = !selectedFile;
    els.clear.disabled = !selectedFile && els.results.hidden;
  };

  const setFile = (file) => {
    clearResults();
    selectedFile = null;
    if (previewUrl) {
      URL.revokeObjectURL(previewUrl);
      previewUrl = null;
    }
    const problem = validateFile(file);
    if (problem) {
      showError(problem);
      els.previewWrap.hidden = true;
      updateButtons();
      return;
    }
    showError("");
    selectedFile = file;
    previewUrl = URL.createObjectURL(file);
    els.preview.src = previewUrl;
    els.fileName.textContent = `${file.name} · ${formatSize(file.size)}`;
    els.previewWrap.hidden = false;
    updateButtons();
  };

  const setBusy = (busy) => {
    els.loading.hidden = !busy;
    els.analyze.disabled = busy || !selectedFile;
    els.fileInput.disabled = busy;
  };

  const candidateRow = (candidate, index, uncertain) => {
    const li = document.createElement("li");
    const head = document.createElement("div");
    head.className = "cand-head";

    const name = document.createElement("span");
    name.className = "cand-name";
    name.textContent = `${index + 1}. ${candidate.name_ko}`;
    const label = document.createElement("span");
    label.className = "cand-label";
    label.textContent = `(${candidate.label})`;
    name.append(label);

    const pct = document.createElement("span");
    pct.className = "cand-pct";
    pct.textContent = `${(candidate.confidence * 100).toFixed(1)}%`;

    head.append(name, pct);

    const bar = document.createElement("div");
    bar.className = "bar";
    bar.setAttribute("aria-hidden", "true");
    const fill = document.createElement("span");
    fill.style.width = `${Math.max(0, Math.min(100, candidate.confidence * 100))}%`;
    bar.append(fill);

    li.append(head, bar);
    if (uncertain) li.dataset.uncertain = "true";
    return li;
  };

  const renderResult = (data) => {
    lastPrediction = data;
    const uncertain = data.status !== "ok";

    els.results.hidden = false;
    els.badge.textContent = uncertain ? "인식 불확실" : "추정 결과";
    els.badge.className = `badge ${uncertain ? "uncertain" : "ok"}`;
    els.message.textContent = data.message;
    els.topList.classList.toggle("dim", uncertain);
    els.topList.replaceChildren(...data.top_k.map((c, i) => candidateRow(c, i, uncertain)));

    if (!uncertain) {
      const rows = data.top_k.map((c) => {
        const tr = document.createElement("tr");
        const td1 = document.createElement("td");
        td1.textContent = c.name_ko;
        const td2 = document.createElement("td");
        td2.textContent = c.nutrition ? c.nutrition.serving : "-";
        const td3 = document.createElement("td");
        td3.textContent = c.nutrition ? `${c.nutrition.kcal} kcal` : "-";
        tr.append(td1, td2, td3);
        return tr;
      });
      els.nutritionBody.replaceChildren(...rows);
      els.nutritionWrap.hidden = false;
    } else {
      els.nutritionBody.replaceChildren();
      els.nutritionWrap.hidden = true;
    }

    els.fbThanks.hidden = true;
    els.fbCorrection.hidden = true;
    els.fbYes.disabled = false;
    els.fbNo.disabled = false;
    els.results.scrollIntoView({ behavior: "smooth", block: "start" });
    updateButtons();
  };

  const analyze = async () => {
    if (!selectedFile) return;
    setBusy(true);
    showError("");
    clearResults();
    try {
      const res = await fetch("/api/predict", {
        method: "POST",
        headers: { "Content-Type": selectedFile.type },
        body: selectedFile,
      });
      const data = await res.json().catch(() => null);
      if (!res.ok) {
        showError(data?.error?.message || `분석에 실패했습니다 (HTTP ${res.status}).`);
        return;
      }
      renderResult(data);
    } catch (err) {
      showError("서버에 연결할 수 없습니다. 터미널에서 ./run.sh 가 실행 중인지 확인하세요.");
    } finally {
      setBusy(false);
      updateButtons();
    }
  };

  const sendFeedback = async (correct, actualLabel) => {
    if (!lastPrediction) return;
    els.fbYes.disabled = true;
    els.fbNo.disabled = true;
    els.fbSend.disabled = true;
    try {
      const res = await fetch("/api/feedback", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          prediction_id: lastPrediction.prediction_id,
          correct,
          actual_label: actualLabel,
        }),
      });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      els.fbCorrection.hidden = true;
      els.fbThanks.textContent = "피드백 감사합니다. 모델 개선에 사용됩니다.";
      els.fbThanks.hidden = false;
    } catch (err) {
      els.fbYes.disabled = false;
      els.fbNo.disabled = false;
      els.fbThanks.textContent = "피드백 전송에 실패했습니다. 잠시 후 다시 시도하세요.";
      els.fbThanks.hidden = false;
    } finally {
      els.fbSend.disabled = false;
    }
  };

  const loadHealth = async () => {
    try {
      const res = await fetch("/health");
      const h = await res.json();
      if (h.model_loaded) {
        els.modelLine.textContent =
          `모델: ${h.model.model_id} · 버전 ${h.model.model_version} · 리비전 ${h.model.revision.slice(0, 8)} · CPU 추론`;
      } else {
        els.modelLine.textContent = `모델 로드 실패: ${h.load_error || "원인 미상"}`;
      }
      maxBytes = h.inference.max_upload_mb * 1024 * 1024;
      els.maxMb.textContent = String(h.inference.max_upload_mb);
    } catch (err) {
      els.modelLine.textContent = "서버에 연결할 수 없습니다.";
    }
  };

  const loadCalories = async () => {
    try {
      const res = await fetch("/api/calories");
      const data = await res.json();
      els.calNotice.textContent = data.notice;
      els.calBody.replaceChildren(
        ...data.items.map((item) => {
          const tr = document.createElement("tr");
          const td1 = document.createElement("td");
          td1.textContent = item.name_ko;
          const td2 = document.createElement("td");
          td2.textContent = item.serving;
          const td3 = document.createElement("td");
          td3.textContent = `${item.kcal} kcal`;
          tr.append(td1, td2, td3);
          return tr;
        })
      );
      const sorted = [...data.items].sort((a, b) => a.name_ko.localeCompare(b.name_ko, "ko"));
      els.fbLabel.append(
        ...sorted.map((item) => {
          const opt = document.createElement("option");
          opt.value = item.label;
          opt.textContent = `${item.name_ko} (${item.label})`;
          return opt;
        })
      );
    } catch (err) {
      els.calNotice.textContent = "칼로리 표를 불러오지 못했습니다.";
    }
  };

  els.fileInput.addEventListener("change", () => setFile(els.fileInput.files[0] || null));
  els.analyze.addEventListener("click", analyze);
  els.clear.addEventListener("click", () => {
    els.fileInput.value = "";
    setFile(null);
    showError("");
    updateButtons();
  });
  els.fbYes.addEventListener("click", () => sendFeedback(true, null));
  els.fbNo.addEventListener("click", () => {
    els.fbCorrection.hidden = false;
    els.fbLabel.focus();
  });
  els.fbSend.addEventListener("click", () => sendFeedback(false, els.fbLabel.value || null));

  updateButtons();
  loadHealth();
  loadCalories();
})();
