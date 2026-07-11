# MergeMate

MergeMate, büyük monolith ve Maven multi-module projelerde **PR/MR açılmadan önce** lokal olarak çalışan bir Test Impact Analysis ve Validation Planner aracıdır.

Amaç: Jenkins üzerinde her PR için yaklaşık 1 saat süren full build'lerin tükettiği agent kapasitesini azaltmak. MergeMate yalnızca gerçekten etkilenen modülleri ve testleri seçer.

## Temel kullanım

```bash
# Sadece analiz — Maven çalıştırmaz
mergemate analyze --target origin/premaster

# Seçili testleri çalıştır
mergemate test --target origin/premaster

# Etkilenen modülleri compile et
mergemate compile --target origin/premaster

# Etkilenen modülleri verify et
mergemate verify --target origin/premaster

# Kaynak branch açıkça belirtmek için
mergemate analyze --source HEAD --target origin/premaster

# Maven profilleri ile
mergemate analyze --target origin/premaster --profiles local,dev

# JSON çıktısı
mergemate analyze --target origin/premaster --json
```

## Nasıl çalışır

1. **Merge-base diff**: `git merge-base` üzerinden gerçek değişen dosyaları bulur (iki noktalı diff değil).
2. **Modül eşleme**: Her değişen dosyayı en derin Maven modülüne atar.
3. **Etki analizi**: Ters bağımlılık grafı üzerinden etkilenen downstream modülleri bulur.
4. **Risk değerlendirmesi**: Root POM değişikliği, kritik modüller, yüksek etki oranı → full build önerir.
5. **Maven komutu üretir**: `./mvnw -pl :order-service,:checkout-api -am test` gibi hedefli komutlar.
6. **Geçici worktree**: Kullanıcının çalışma kopyasına dokunmaz; geçici git worktree kullanır.

## Örnek analiz çıktısı

```text
MergeMate Impact Analysis

Source: HEAD
Target: origin/premaster
Merge base: abc1234

JDK:
  Required: 17
  Maven runtime: 17.0.12
  Compatible: yes
  Detected from: root pom.xml -> maven.compiler.release

Changed modules:
  order-service

Affected modules:
  order-service       changed
  checkout-api        dependent
  shared-common       dependency

Risk: MEDIUM
Full validation recommended: NO

Recommended Maven command:
  ./mvnw -pl :order-service,:checkout-api -am test
```

## Kurulum

```bash
pip install -e ".[dev]"
```

## Çalışma modu: Lokal Worktree (varsayılan)

Kullanıcının mevcut lokal ortamını kullanır:
- Maven executable veya Maven wrapper (`./mvnw` öncelikli)
- Mevcut JDK ve `JAVA_HOME`
- Lokal `.m2` cache
- VPN ve Nexus erişimi

Kullanıcının working tree'sine **dokunulmaz**. Geçici `git worktree` oluşturulur, iş bitince temizlenir (hata durumunda da garanti).

## JDK tespiti

POM dosyalarından otomatik tespit:
1. `maven.compiler.release` property
2. `maven-compiler-plugin` `<release>` configuration
3. `java.version` / `jdk.version` property
4. `maven.compiler.source` / `target` (fallback)
5. Parent POM zinciri takibi

Uyumsuzluk durumunda anlaşılır hata:
```text
Project requires JDK 17 but Maven is running with JDK 11.
Configure JAVA_HOME or Maven Toolchains before running validation.
```

## Config dosyası

Repo root'unda opsiyonel `.mergemate.yml`:

```yaml
targetBranch: origin/premaster

impact:
  maxDepth: 3
  fullBuildThreshold: 0.60

modules:
  alwaysFullBuild:
    - shared-common
    - platform-core

files:
  fullBuildPatterns:
    - "**/application*.yml"
    - "**/db/changelog/**"

timeouts:
  testSeconds: 1800
  verifySeconds: 3600
```

## Mimari

```
mergemate/
  domain/        Domain modelleri (ChangedFile, MavenModule, ImpactAnalysis, ...)
  git/           merge-base diff motoru, geçici worktree yönetimi
  maven/         Wrapper tespiti, JDK tespiti, proje yükleyici
  impact/        Modül grafiği, dosya eşleyici, risk motoru, ImpactAnalyzer
  execution/     ExecutionAdapter ABC, LocalWorktreeAdapter, CurrentWorkspaceAdapter
  reporting/     Console ve JSON raporlama
  config/        .mergemate.yml yükleyici
  cli/           argparse CLI giriş noktası

# Opsiyonel Docker katmanı (mevcut, ikincil adapter):
forge_worker/    Git guard, validation lifecycle, hardened Dockerfile
forge_orchestrator/  Docker Worker, Orchestrator, orphan reaper
forge_api/       FastAPI REST API + SQLite repository
forge_spi/       ValidationStep ABC + Git/Maven plugin'leri
forge_analysis/  Hata analizi (FailureAnalyzer)
web/             React + Vite + TypeScript dashboard
```

## Testler

```bash
py -m pytest tests/ -v

# Entegrasyon testleri (gerçek git gerektirir)
py -m pytest tests/ -v -m integration
```

**270 test, tümü geçiyor.**

| Faz | İçerik | Testler |
|-----|--------|---------|
| 1 | Domain modeller, Git diff, Worktree adapter, JDK tespiti, CLI | 43 |
| 2 | Maven proje yükleyici, modül grafiği, dosya eşleyici, risk motoru, ImpactAnalyzer, raporlama | 36 |
| Slice 1-7 | forge_* paketleri (orijinal Docker tabanlı altyapı) | 191 |

## Sonraki adımlar (Faz 3-5)

- **Faz 3**: JavaParser tabanlı source analyzer, ters bağımlılık grafiği, test aday puanlama
- **Faz 4**: Compile/verify profilleri, JSON/HTML rapor dosyaları, timeout ve iptal
- **Faz 5**: Docker adapter düzeltmeleri, FastAPI async, web UI adaptasyonu

## Docker modu (opsiyonel)

```bash
# Backend
pip install -e ".[dev]"
docker build -t mergemate-worker:latest forge_worker/
python -m forge_api.main   # → http://localhost:8080

# Frontend
cd web && npm install && npm run dev   # → http://localhost:5173
```
