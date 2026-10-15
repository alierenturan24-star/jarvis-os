# JARVIS Claude Code çalışma kuralları

Bu depo JARVIS OS projesidir. Claude Code bu depoda JARVIS'in kontrollü worker'ı olarak kullanılır.

## Dil ve hedef
- Kullanıcıya ve JARVIS'e dönen sonuçlar Türkçe olmalıdır.
- Mevcut mimariyi ve onay kapılarını koru; gereksiz yeni sistem icat etme.
- Gerçek sonucu, dosyayı ve test kanıtını uydurma. Çalışmayan şeyi çalışıyor gibi gösterme.
- Video yayınlama ve gerçek para işlemi insan onayı olmadan yapılmaz.
- Kimlik bilgisi, API anahtarı, ödeme, commit/push ve yıkıcı git işlemleri alt ajanlara devredilmez.

## Agency Agents
Bu projede `.claude/agents/` altında msitarzewski/agency-agents kaynaklı, proje için salt-okunur danışman ajanlar bulunur.

Planlama / inceleme çağrılarında yalnız gerçekten faydalıysa en fazla 2 uzmanı kullan:
- **Agents Orchestrator**: birden fazla uzman gerektiğinde görev bölme ve sonuç birleştirme.
- **Multi-Agent Systems Architect**: JARVIS ajan mimarisi, izinler, fallback, recovery ve gözlemlenebilirlik.
- **AI Engineer**: model/provider entegrasyonu, routing ve AI üretim hattı.
- **Code Reviewer**: değişiklik öncesi/sonrası doğruluk, güvenlik ve regression kontrolü.
- **Prompt Engineer**: provider promptları, çıktı sözleşmeleri ve hallucination azaltma.
- **Video Streaming Engineer**: FFmpeg, codec, render, ses/video zamanlaması ve teknik medya sorunları.
- **Trend Researcher**: güncel konu adayları ve fırsat taraması; yalnız gerçek araştırma gerektiğinde.
- **Research Synthesist**: birden çok kaynağın aynı olayı doğrulayıp doğrulamadığını ve kanıt kalitesini inceleme.
- **Content Creator**: araştırmayla doğrulanmış olgulardan özgün kısa video senaryosu, sahne ve başlık üretimi.

## JARVIS video akışı
Güncel haberden kısa video görevlerinde:
1. JARVIS Research çıktısı varsa bunu birincil kanıt olarak kabul et; yeni olgu uydurma.
2. Kanıt kalitesi şüpheliyse Research Synthesist kullan.
3. Senaryo/Shorts kurgusu için Content Creator kullan.
4. FFmpeg/render/codec/ses-zamanlama problemi varsa Video Streaming Engineer kullan.
5. Kod değişikliği gerekiyorsa Code Reviewer ile riskleri kontrol et.
6. Public Domain / CC0 / CC BY şartı verilmişse CC BY-SA/NC/ND veya lisansı belirsiz medyayı kabul etme.
7. MP4 gerçekten oluşmadan veya kalite kapıları geçmeden "tamamlandı" deme.

## Yetki sınırı
- Agency ajanları danışmandır; proje dosyalarını doğrudan değiştirmeleri gerekmez.
- JARVIS'in repo-edit yolu kendi ActionPolicy ve Claude Code allow-list sınırlarını kullanır.
- Edit modunda subagent/Task aracı mevcut değilse bunu aşmaya çalışma; ana Claude mevcut izinlerle düzenlemeyi yapar.
- Test çalıştırma JARVIS'in mevcut test/onay mekanizmasından geçer.
