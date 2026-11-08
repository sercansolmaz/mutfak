# Mutfak

*English: [README.md](README.md)*

Mutfak, YouTube kanalınızın yeni yorumlarını her gece toplar, bir dil modeliyle öngörülere çevirir
ve onayladığınız video konularını izleyicilerinizin oylamasına açar. Kendi sunucunuzda tek komutla
çalışır.

Kanalınız dükkansa, burası izleyici siparişlerinin hazırlandığı mutfak.

## Ne yapar?

1. **Toplayıcı:** Her gece 03:00'te (Europe/Istanbul) YouTube Data API v3 ile tüm kanalın yeni
   yorumlarını çeker. Yalnızca API anahtarı gerekir, OAuth yok. Normal bir gece günlük 10.000
   birimlik ücretsiz kotanın yaklaşık 1 birimini harcar.
2. **Analiz:** [OpenRouter](https://openrouter.ai) üzerinden bir dil modeli (varsayılan
   `deepseek/deepseek-v4.1-flash`, değiştirilebilir) şunları çıkarır:
   - konu taleplerini gruplar,
   - cevabınızı bekleyen soruları bulur,
   - tekrar eden eleştirileri ayırır,
   - izleyicilerin bahsettiği yeni haber ve ürünleri listeler.

   Ürün, şirket ve model adları kartlarda açıkça yazılır.
3. **Özel panel** (`/panel`, şifreli): Öngörü kartları, cevap bekleyen sorular ve onay kuyruğu.
   Sistemin bulduğu hiçbir konu siz onaylamadan yayınlanmaz.
4. **Halka açık İstek Panosu** (`/mutfak`): Onayladığınız konular sipariş fişleri olarak görünür,
   ziyaretçiler oy verir. Ziyaretçi yalnızca oy verebilir.
5. **Telegram botu** (isteğe bağlı): Sabah kısa bir rapor, onay bekleyen konular için Onayla ve
   Reddet düğmeleri. Yalnızca size cevap verir.

```
YouTube API ──> toplayıcı ──> SQLite <── analiz ──> OpenRouter
                                 │
           ┌─────────────────────┼─────────────────────┐
       özel panel           İstek Panosu          Telegram botu
        (/panel)             (/mutfak)         (rapor + düğmeler)
```

## Gizlilik ve güvenlik

- **YouTube'un 30 gün kuralı:** 30 günden eski yorumların metni ve yazar adı her gece silinir.
  Konular ve sayılar kalır.
- **Yazar adları dil modeline hiç gitmez.** Yorumlar yalnızca kısa kimliklerle gönderilir, `@adlar`
  maskelenir.
- **Talimat denemeleri (prompt injection):**
  - Yorumlar modele JSON verisi olarak gider; sistem mesajı bunların talimat değil veri olduğunu söyler.
  - Modelin hiçbir aracı yoktur.
  - Modelin JSON cevabı doğrulanır: bilinmeyen kimlikler ve türler, bağlantılar ve fazla uzun metinler atılır.
  - Hiçbir şey otomatik yayınlanmaz.
- **İstek Panosu'nda** yorumcu adı, yorum metni ve yorumlardan hesaplanan sayı görünmez. Yalnızca
  ziyaretçi oyları sayılır.
- **Oylar:**
  - Her ziyaretçi çerezi bir konuya 1 oy verebilir.
  - Aynı IP adresinden bir konuya en fazla 20 oy verilebilir.
  - IP adresi yalnızca anahtarlı bir özet (hash) olarak saklanır.
  - İkinci dokunuş oyu geri alır.
- **Telegram mesajlarında** yalnızca konu başlıkları ve sayılar bulunur.
- **Ziyaretçiler hiçbir dış adrese istek göndermez.** Font
  ([Recursive](https://github.com/arrowtype/recursive), OFL lisanslı) sizin sunucunuzdan sunulur.

## Kurulum

Docker ve Docker Compose kurulu bir Linux sunucu, bir alan adı (ya da alt alan adı) ve şu anahtarlar
gerekir:

| Anahtar | Nereden alınır? |
|---|---|
| `YOUTUBE_API_KEY` | Google Cloud Console → APIs & Services → Credentials. Yalnızca "YouTube Data API v3" ile sınırlayın. |
| `YOUTUBE_CHANNEL_ID` | YouTube Studio → Ayarlar → Kanal → Gelişmiş ayarlar (`UC` ile başlar) |
| `OPENROUTER_API_KEY` | https://openrouter.ai/keys |
| `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID` | İsteğe bağlı. Botu @BotFather ile oluşturun, chat ID'nizi @userinfobot'tan öğrenin. |

```sh
git clone <bu depo> mutfak && cd mutfak
cp .env.example .env && chmod 600 .env
# .env dosyasını doldurun (her değer dosyada açıklanmıştır), sonra:
docker compose up -d --build
```

Önce alan adınız için sunucunun IP adresini gösteren bir A kaydı ekleyin. Caddy HTTPS sertifikasını
kendisi alır. Tüm servisler kendiliğinden yeniden başlar; sunucu yeniden açıldığında da.

İlk çalışmada son 30 günün yorumları çekilir. Sonraki gecelerde yalnızca yeni yorumlar gelir.

### İşe yarar komutlar

```sh
docker compose exec worker python -m app.worker once     # gece işini şimdi çalıştır
docker compose exec worker python -m app.worker report   # Telegram raporunu şimdi gönder
docker compose logs -f worker                            # gece işini izle
```

### Ayarlar (`.env`)

| Ayar | Varsayılan | Anlamı |
|---|---|---|
| `DOMAIN` | | Pano ve panelin alan adı |
| `PANEL_PASSWORD` | | `/panel` giriş şifresi |
| `SECRET_KEY` | | Çerezler ve IP özetleri için uzun rastgele değer |
| `OPENROUTER_MODEL` | `deepseek/deepseek-v4.1-flash` | Herhangi bir OpenRouter model adı |
| `RUN_AT` | `03:00` | Gece işinin saati (Europe/Istanbul) |
| `REPORT_AT` | `09:00` | Telegram sabah raporunun saati |

## Klasör yapısı

```
app/
  collector.py   YouTube'dan yorum çekme
  analyzer.py    OpenRouter çağrısı, talimat metni ve çıktı doğrulama
  db.py          SQLite şeması ve 30 gün kuralı
  telegram.py    rapor ve Onayla/Reddet düğmeleri
  worker.py      gece zamanlayıcısı ve Telegram dinleyicisi
  web.py         Flask: /mutfak, /panel
  templates/, static/
compose.yaml  Dockerfile  Caddyfile  .env.example
```

Üç konteyner çalışır:
- `web`: Flask + gunicorn
- `worker`: zamanlayıcı + Telegram
- `caddy`: HTTPS

Tüm veriler `data` volume'ündeki tek bir SQLite dosyasında durur.

## Kodlama ajanını ayrı ve yetkisiz bir kullanıcıyla çalıştırmak

Bu proje, video sade kalsın diye `root` olarak çalışan bir yapay zekâ kodlama ajanıyla (Claude Code)
yapıldı. Ciddi kullanımda böyle yapmayın.

**Neden?** Ajan güvenilmeyen metinlerle çalışır. Web sayfaları, API cevapları ve bu projede YouTube
yorumları talimat içerebilir. Root yetkisiyle tek bir hata ya da başarılı bir talimat saldırısı
şunları yapabilir:
- makinedeki bütün anahtarları okuyabilir,
- sistem dosyalarını değiştirebilir,
- verileri silebilir.

Ayrı bir kullanıcı, olası zararı o kullanıcının erişebildiği dosyalarla sınırlar.

**Nasıl?**

1. Sudo yetkisi olmayan bir kullanıcı açın: `adduser --disabled-password agent`. Ona yalnızca proje
   klasörünü verin: `chown -R agent: /srv/mutfak`.
2. Anahtarları ondan uzak tutun. `.env` dosyası kendi kullanıcınıza ait olsun ve `chmod 600` ile
   korunsun; ajan anahtarları okuyamaz. Claude Code'da ayrıca `.claude/settings.json` içindeki
   izinlere `"deny": ["Read(.env)"]` ekleyebilirsiniz.
3. **Ajanı `docker` grubuna eklemeyin.** Docker grubuna üyelik root yetkisine eşdeğerdir. Ajan kodu
   düzenlesin ve testleri çalıştırsın; `docker compose up -d --build` komutunu siz çalıştırın. Ajanın
   konteyner çalıştırması gerekiyorsa rootless Docker kullanın.
4. Yayına almadan önce ajanın commit'lerini gözden geçirin.

## Lisans

[MIT](LICENSE). Recursive fontu SIL Open Font License ile lisanslıdır
([app/static/fonts/OFL.txt](app/static/fonts/OFL.txt)).
