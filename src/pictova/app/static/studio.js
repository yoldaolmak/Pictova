"use strict";

(function () {
  const byId = (id) => document.getElementById(id);
  const tokenFromUrl = new URLSearchParams(window.location.hash.slice(1)).get("token");
  let accessToken = tokenFromUrl || "";
  let plan = null;
  let selected = new Set();
  let running = false;
  let previewObjects = [];

  // Keep the bootstrap token only in this page's memory, never in browser
  // history, local storage, HTTP query parameters or third-party image URLs.
  if (window.location.hash) {
    window.history.replaceState(null, "", window.location.pathname);
  }
  if (!accessToken) byId("auth-panel").hidden = false;

  function message(text, error) {
    const notice = byId("notice");
    notice.textContent = String(text || "");
    notice.classList.toggle("error", !!error);
    notice.hidden = !text;
  }

  function setBusy(value) {
    running = value;
    byId("plan-button").disabled = value;
    refreshApproval();
  }

  async function api(path, payload) {
    if (!accessToken) throw new Error("Önce yerel erişim anahtarını girin");
    const options = {
      headers: { Authorization: "Bearer " + accessToken },
      cache: "no-store",
      credentials: "omit"
    };
    if (payload !== undefined) {
      options.method = "POST";
      options.headers["Content-Type"] = "application/json";
      options.body = JSON.stringify(payload);
    }
    const response = await fetch(path, options);
    const data = await response.json();
    if (!response.ok || data.status === "failed") {
      throw new Error(data.warning || (data.warnings && data.warnings[0]) || "İstek gerçekleştirilemedi");
    }
    return data;
  }

  function clearPreviews() {
    for (const url of previewObjects) URL.revokeObjectURL(url);
    previewObjects = [];
  }

  async function loadLocalPreview(img, candidate, currentPlanId) {
    const link = "/studio/preview?plan=" + encodeURIComponent(currentPlanId) +
      "&candidate=" + encodeURIComponent(candidate.id);
    try {
      const response = await fetch(link, {
        headers: { Authorization: "Bearer " + accessToken },
        cache: "no-store",
        credentials: "omit"
      });
      if (!response.ok) throw new Error("Preview unavailable");
      const blob = await response.blob();
      if (plan && plan.plan_id === currentPlanId) {
        const object = URL.createObjectURL(blob);
        previewObjects.push(object);
        img.src = object;
      }
    } catch (_) {
      img.alt = "Yerel görselin önizlemesi yüklenemedi";
    }
  }

  function makeElement(tag, className, text) {
    const element = document.createElement(tag);
    if (className) element.className = className;
    if (text !== undefined) element.textContent = String(text);
    return element;
  }

  function candidateCard(candidate) {
    const card = makeElement("article", "candidate");
    const preview = makeElement("div", "candidate-preview");
    const img = document.createElement("img");
    img.loading = "lazy";
    img.alt = "Görsel adayı: " + candidate.title;
    img.referrerPolicy = "no-referrer";
    if (candidate.local_preview) {
      preview.appendChild(img);
      loadLocalPreview(img, candidate, plan.plan_id);
    } else if (candidate.preview_url && candidate.preview_url.startsWith("https://")) {
      img.src = candidate.preview_url;
      preview.appendChild(img);
    } else {
      preview.appendChild(makeElement("div", "placeholder", candidate.reason || "Önizleme yok"));
    }
    card.appendChild(preview);

    const detail = makeElement("div", "candidate-details");
    const top = makeElement("div", "candidate-head");
    const source = makeElement(
      "span",
      "source-badge" + (candidate.paid ? " paid-badge" : ""),
      candidate.source === "deposit" ? "DepositPhotos · lisanslı" :
        candidate.source === "local" ? "Yerel arşiv" : "iCloud"
    );
    top.appendChild(source);

    const label = makeElement("label", "select-control");
    const checkbox = document.createElement("input");
    checkbox.type = "checkbox";
    checkbox.checked = candidate.available;
    checkbox.disabled = !candidate.available;
    checkbox.setAttribute("aria-label", candidate.heading + " için görsel seçimi");
    if (candidate.available) selected.add(candidate.id);
    checkbox.addEventListener("change", function () {
      if (checkbox.checked) selected.add(candidate.id);
      else selected.delete(candidate.id);
      card.classList.toggle("selected", checkbox.checked);
      refreshApproval();
    });
    label.appendChild(checkbox);
    label.appendChild(makeElement("span", "", "Seç"));
    top.appendChild(label);
    detail.appendChild(top);
    detail.appendChild(makeElement("h4", "", candidate.title));
    detail.appendChild(makeElement(
      "p", "", candidate.available ? "Aday görsel — yayın öncesi inceleyin." : candidate.reason
    ));
    const heading = makeElement("div", "heading-target");
    heading.appendChild(makeElement("strong", "", "H" + candidate.level + " →"));
    heading.appendChild(makeElement("span", "", candidate.heading));
    detail.appendChild(heading);
    card.appendChild(detail);
    card.classList.toggle("selected", candidate.available);
    card.classList.toggle("unavailable", !candidate.available);
    return card;
  }

  function refreshApproval() {
    const total = selected.size;
    byId("selection-count").textContent = total + " görsel seçildi";
    const paid = !!(plan && plan.candidates.some((c) => selected.has(c.id) && c.paid));
    byId("paid-line").hidden = !paid;
    if (!paid) byId("confirm-paid").checked = false;
    byId("apply-button").disabled = running || !plan || total === 0 || !byId("confirm").checked ||
      (paid && !byId("confirm-paid").checked);
  }

  function renderPlan(data) {
    clearPreviews();
    plan = data;
    selected = new Set();
    byId("confirm").checked = false;
    byId("confirm-paid").checked = false;
    byId("article-title").textContent = data.post.title || "Başlıksız yazı";
    byId("article-meta").textContent = data.post.site + " · WordPress ID " + data.post.post_id;
    byId("plan-state").textContent = data.candidates.length + " aday bulundu";
    byId("section-count").textContent = (data.headings || []).length + " bölüm incelendi";
    byId("empty-state").hidden = true;
    byId("plan-section").hidden = false;

    const grid = byId("candidate-grid");
    grid.replaceChildren();
    for (const candidate of data.candidates) grid.appendChild(candidateCard(candidate));

    const matched = new Set(data.candidates.map((c) => c.heading + "|" + c.level));
    const unmatched = (data.headings || []).filter((h) => !matched.has(h.text + "|" + h.level));
    const none = byId("unmatched");
    none.hidden = unmatched.length === 0 && data.candidates.length !== 0;
    if (!none.hidden) {
      none.textContent = data.candidates.length ?
        unmatched.length + " bölüm için doğrulanmış görsel bulunamadı. Bu bölümler boş kalacak." :
        "Bu yazıda doğrulanmış aday bulunamadı. Hiçbir görsel yayımlanamaz.";
    }

    const warnings = byId("warnings");
    const values = (data.warnings || []).filter(Boolean).slice(0, 4);
    warnings.hidden = !values.length;
    warnings.textContent = values.join(" · ");
    refreshApproval();
  }

  async function pollJob(jobId) {
    const deadline = Date.now() + 10 * 60 * 1000;
    while (Date.now() < deadline) {
      const answer = await api("/jobs/" + encodeURIComponent(jobId));
      const job = answer.job;
      if (job.status === "success" || job.status === "failed") {
        const result = job.result || {};
        const inserted = Number(result.inserted_blocks || 0);
        const uploaded = Array.isArray(result.uploaded_media_ids) ? result.uploaded_media_ids.length : 0;
        const warnings = Array.isArray(result.warnings) ? result.warnings.filter(Boolean) : [];
        const success = result.status === "success" || (inserted > 0 && result.status === "partial");
        message(
          success ?
            "İşlem tamamlandı. WordPress'e " + uploaded + " medya yüklendi; " +
            inserted + " blok yerleştirildi." + (warnings.length ? " Uyarı: " + warnings[0] : "") :
            "Yayımlama tamamlanamadı. " +
            (warnings[0] || job.error || "İşlem sonucu ve WordPress içeriğini kontrol edin."),
          !success
        );
        byId("plan-state").textContent = success ? "Yayımlandı" : "İşlem sonuçlandı";
        return;
      }
      await new Promise((resolve) => setTimeout(resolve, 1300));
    }
    message("İşlem devam ediyor olabilir. CLI ve WordPress üzerinden kontrol edin; yeniden onaylamayın.", true);
  }

  byId("connect").addEventListener("click", function () {
    const value = byId("token").value.trim();
    if (value.length < 32) {
      message("En az 32 karakterlik yerel erişim anahtarı gerekli.", true);
      return;
    }
    accessToken = value;
    byId("token").value = "";
    byId("auth-panel").hidden = true;
    message("Yerel bağlantı anahtarı bu sekmede etkin. Yazı URL'si girebilirsiniz.", false);
  });

  byId("plan-form").addEventListener("submit", async function (event) {
    event.preventDefault();
    if (running) return;
    setBusy(true);
    message("Yazı okunuyor, kaynaklar araştırılıyor ve bölüm eşleşmeleri hazırlanıyor…", false);
    byId("plan-state").textContent = "Plan hazırlanıyor";
    try {
      const data = await api("/studio/plan", {
        url: byId("post-url").value.trim(),
        count: Number(byId("image-count").value)
      });
      renderPlan(data);
      message(data.candidates.length ? "Plan hazır. Görselleri tek tek inceleyip istemediklerinizi eleyin." :
        "Bu yazı için güvenle önerilebilecek görsel bulunamadı.", false);
    } catch (error) {
      byId("plan-state").textContent = "Plan oluşturulamadı";
      message(error.message, true);
    } finally {
      setBusy(false);
    }
  });

  byId("select-none").addEventListener("click", function () {
    selected.clear();
    for (const checkbox of byId("candidate-grid").querySelectorAll('input[type="checkbox"]')) {
      checkbox.checked = false;
      checkbox.closest(".candidate").classList.remove("selected");
    }
    refreshApproval();
  });

  byId("confirm").addEventListener("change", refreshApproval);
  byId("confirm-paid").addEventListener("change", refreshApproval);

  byId("apply-button").addEventListener("click", async function () {
    if (running || !plan || byId("apply-button").disabled) return;
    const planId = plan.plan_id;
    const accepted = Array.from(selected);
    const paid = plan.candidates.some((c) => selected.has(c.id) && c.paid);
    setBusy(true);
    message("Onay kaydediliyor. WordPress yazısı tekrar kontrol edilecek.", false);
    try {
      const response = await api("/studio/apply", {
        plan_id: planId,
        accepted_ids: accepted,
        confirm_paid: paid && byId("confirm-paid").checked
      });
      byId("plan-state").textContent = "Uygulama sürüyor";
      await pollJob(response.job_id);
      plan = null; // One-time approval; a new attempt requires a fresh plan.
    } catch (error) {
      message(error.message + " Tekrar denemek için yeni bir plan oluşturun.", true);
      plan = null;
    } finally {
      setBusy(false);
    }
  });
})();
