# 🗺 Pictova Roadmap

Pictova, içerik odaklı görsel otomasyonunda endüstri standardı olmayı hedefler. Geliştirme yol haritamız, uygulamayı **Premium bir SaaS** ve güçlü bir CLI/API ekosistemine dönüştürmek üzerine kuruludur.

---

## 🎯 Phase 1: Core Intelligence & Native Engine (Q3)
**Hedef:** Temel görsel arama, işleme ve AI-Destekli Metadata motorunun kusursuzlaştırılması.

- [x] **Native Engine Geçişi:** Legacy kodların bırakılıp, modüler (`attach`, `process`, `plan`) mimariye geçilmesi.
- [x] **Heading-Aware Selection:** Yazı içi H2/H3 başlıklarına duyarlı görsel atama ve SEO (slug/title) isimlendirme mekanizması.
- [x] **Vision Chain:** Gemini / Claude / Codex fallback yapısıyla resim piksellerinden kusursuz, anadilinde (TR) alt metin/başlık üretimi.
- [ ] **Multi-Source Fallback:** Semantic Selector başarısız olduğunda otomatik olarak Unsplash API'sine düşme (fallback).

---

## 🚀 Phase 2: Premium Features & Stock Integrations (Q4)
**Hedef:** Ticari (lisanslı) stok sitelerinin entegrasyonu ve kalite standartlarının artırılması.

- [ ] **Pictova Depot (DepositPhotos API):** Semantic search veya Unsplash yetersiz kaldığında lisanslı stok kütüphanelerinden otomatik satın alım ve indirme.
- [ ] **Advanced Quality Gate:** İndirilen resimlerde bulanıklık (blur), çözünürlük veya içerik kalitesi tespiti yaparak düşük kaliteli resimleri eleme sistemi.
- [ ] **WebP Optimization V2:** %100 kayıpsız (lossless) sıkıştırma algoritmalarının entegrasyonu ve EXIF verilerinin tam kontrolü.

---

## 🌐 Phase 3: Platform & UI/UX (Next Year)
**Hedef:** Geliştirici odaklı (CLI) araçtan, son kullanıcıya hitap eden yönetilebilir bir servise dönüşüm.

- [ ] **Meridyen UI Entegrasyonu:** YOOS-APP (İçerik üretim platformu) ile doğrudan görsel iletişim sağlayan web arayüzü.
- [ ] **Job Queue & Persisted Store:** Uzun süren attach görevlerini asenkron yönetmek için Redis / SQLite tabanlı görev kuyruğu (Task Queue).
- [ ] **Custom Prompts:** Kullanıcıların Vision Chain için kendi `system_prompt` yapılarını tanımlayabilmesi (Örn: Sadece teknik terimlerle açıklama yap).

---

## 🧠 Phase 0 (öncelikli): Sözlükten semantiğe

**İlke:** *Koda destinasyon veya belirli bir yazıya ait mantık giremez.* Yer bilgisi
postun kendisinden gelir; eşleşme öğrenilir, elle yazılmaz.

Gerekçe: `Kosova → Kos`, `Ohrid → Türkiye`, kısa sorguya `Turkey` eklenmesi — üçü de
aynı kökten çıktı. Sözlük dünyayı kapsayamıyor; her yeni destinasyon bir yama istiyordu.

- [x] **Adım 1 — Silme:** Destinasyon ve tek-yazıya-ait tüm sabitler kaldırıldı
      (`ISLAND_MAP`, `TR_PROPER`, landmark tablosu, ülke fallback'i, `DESTINATION_COORDINATES`,
      TR↔EN eşdeğer sözlüğü, uygulama-listesi ve "yalnız seyahat" özel mantığı).
      Prensip `test_no_destination_names_remain_in_code` ile 5 modülde kilitlendi.
      Kaybedilen yetenekler 15 `xfail` testiyle belgelendi — Adım 2'nin kabul kriteri.
- [ ] **Adım 2 — Yerleşim davranışını öğren:** Yayında olan 100+ "gezi rehberi /
      gezilecek yerler / nerede nasıl gidilir" postu taranır. Çıkarılacak davranış:
      hangi H başlığa görsel girer, hangisine **girmez**; kaç görsel; nerede tek dikey,
      nerede ikili galeri, hangi nadir durumda üçlü galeri. Bu, draft posta
      "nereye kaç görsel" sorusunu kural yazmadan cevaplar.
- [ ] **Adım 3 — Semantik eşleşme:** Sorgu üretimi ve aday doğrulama, token setleri
      yerine mevcut vision/embedding zincirine (LM Studio → Gemini → OpenAI) taşınır.
      **Fail-closed korunur:** model yeterince emin değilse başlık boş kalır ve
      makbuza gerekçe yazılır.
- [ ] **Adım 4 — Kaynak zinciri:** iCloud Photos + DepositPhotos birincil; Unsplash ve
      2-3 Creative Commons sağlayıcısı fallback.
- [ ] **Adım 5 — İsimlendirme ve caption:** SEO uyumlu, benzersiz, numaralandırmasız
      doğal dosya adı. Caption Kemal Kaya ağzından — kısa, semantik, piksel envanteri
      değil; foto analizini birebir anlatmak zorunda değil.

### Bağlam
Pictova, **Meridyen** sisteminin (yoldaolmak.com ve diğer içerik siteleri) görsel motorudur.
İçerik katmanı YOOS'tur; YOOS evrilerek **Graphova**'ya dönüştü. Graphova'daki know-how
sonraki bir aşamada YOOS'a aktarılacak — bu roadmap'te kayıtlı, şu anki odak değil.

---

> *"The road to seamless visual content is automated, intelligent, and context-aware."*
