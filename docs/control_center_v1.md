# JARVIS Control Center V1

Proje kökünden çalıştırın:

```bash
python control_center.py
```

Panel varsayılan olarak yalnızca `http://127.0.0.1:8765` adresinde dinler.
Terminalde yazdırılan `LOCAL BOOTSTRAP URL` ilk güvenli oturumu açar; URL'deki
token başarılı girişten sonra adres çubuğundan kaldırılır.

Control Center mevcut `JarvisRuntime`, mission/task kayıtları, department
agent'ları, approval store ve `ProviderExecutionHistory` üzerinde bir
gözlem/yönetim katmanıdır. Ayrı bir agent, task veya provider sistemi kurmaz.

Read API'leri:

- `GET /api/health`
- `GET /api/dashboard`
- `GET /api/workers`
- `GET /api/tasks`
- `GET /api/approvals`
- `GET /api/providers`
- `GET /api/costs`
- `GET /api/youtube`
- `GET /api/finance`
- `GET /api/research`
- `GET /api/logs`

Maliyet, YouTube analytics veya başka bir metrik backend tarafından
ölçülmüyorsa API ve arayüz bunu boş durum olarak gösterir. Secret değerleri
provider cevaplarına eklenmez; operasyon logları UI'ya gönderilmeden önce
sanitize edilir. Finance görünümü `PAPER / SIMULATION` modundadır ve gerçek
emir execution endpoint'i yoktur.
