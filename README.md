# MergeMate

MergeMate, büyük monolith ve Maven multi-module projelerde **PR/MR açılmadan önce** lokal olarak çalışan bir Test Impact Analysis ve Validation Planner aracıdır.

Amaç: Jenkins üzerinde her PR için yaklaşık 1 saat süren full build'lerin tükettiği agent kapasitesini azaltmak. MergeMate yalnızca gerçekten etkilenen modülleri ve testleri seçer.

## Kurulum

```bash
pip install -e ".[dev]"

# Java analizi için (opsiyonel):
pip install -e ".[java-analysis]"
```

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

# Seçenekler
mergemate analyze --source HEAD --target origin/premaster
mergemate analyze --target origin/premaster --profiles local,dev
mergemate analyze --target origin/premaster --impact-depth 3
mergemate analyze --target origin/premaster --json
```

## Örnek çıktı

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

Changed Java production files:
  services/order-service/src/main/java/.../OrderService.java

Selected tests:
  OrderServiceTest               HIGH      0.85
  CheckoutFacadeTest             MEDIUM    0.52

  Reasons (OrderServiceTest):
    - Name matches changed class OrderService
    - Directly imports com.example.OrderService

Risk: MEDIUM
Full validation recommended: NO

Recommended Maven command:
  ./mvnw -pl :order-service,:checkout-api -am \
    -Dtest=OrderServiceTest,CheckoutFacadeTest test
```

## Nasıl çalışır

1. **Merge-base diff** — `git merge-base` üzerinden gerçek değişen dosyaları bulur
2. **Modül eşleme** — Her dosyayı en derin Maven modülüne atar (deepest ancestor wins)
3. **Etki analizi** — Ters bağımlılık grafiği üzerinden downstream modülleri bulur
4. **Java source analizi** — `javalang` AST parser ile import/type reference analizi; 3 seviyeli test seçimi
5. **Test puanlama** — Her test adayı ağırlıklı sinyaller ile puanlanır (HIGH/MEDIUM/LOW)
6. **Risk değerlendirmesi** — Root POM, kritik modüller, yüksek etki oranı → full build önerir
7. **Maven komutu üretir** — `./mvnw -pl :mod-a,:mod-b -am -Dtest=... test`
8. **Geçici worktree** — Kullanıcının working copy'sine dokunmaz; `git worktree add --detach` kullanır

## Rapor dosyaları

Her validation çalışmasında `.mergemate/runs/<run-id>/` altına yazılır:

```
.mergemate/runs/<run-id>/
  report.json       # Tam yapılandırılmış rapor (JSON)
  report.html       # Standalone dark-mode HTML rapor (dış bağımlılık yok)
  stdout.log        # Maven stdout
  stderr.log        # Maven stderr
```

### HTML Rapor

`report.html` dosyası external CSS/JS gerektirmez, tek başına açılabilir.
Şu bölümleri içerir: Git değişiklikleri, JDK bilgisi, etkilenen modüller,
risk değerlendirmesi, seçili testler, Maven komutu, Surefire/Failsafe sonuçları.

### Surefire/Failsafe sonuçları

Maven çalıştıktan sonra tüm `target/surefire-reports/` ve `target/failsafe-reports/`
klasörlerindeki `TEST-*.xml` dosyaları otomatik olarak parse edilir.
`report.json` içinde `surefire` bloğu olarak yer alır.

## Config dosyası

Repo root'unda opsiyonel `.mergemate.yml`:

```yaml
targetBranch: origin/premaster

impact:
  maxDepth: 3
  fullBuildThreshold: 0.60

jdk:
  strict: true
  allowNewerMajorVersion: true

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

## JDK tespiti

POM dosyalarından otomatik (öncelik sırası):
1. `maven.compiler.release` property
2. `maven-compiler-plugin <release>` configuration
3. `java.version` / `jdk.version` property
4. `maven.compiler.source` / `target` fallback
5. Parent POM zinciri takibi

```text
Project requires JDK 17 but Maven is running with JDK 11.

Detected from:
  root pom.xml -> maven.compiler.release

Configure JAVA_HOME or Maven Toolchains before running validation.
```

## REST API entegrasyonu

`forge_api` FastAPI sunucusu çalışırken local analiz şu endpoint ile tetiklenebilir:

```bash
curl -X POST http://localhost:8080/api/v1/analyze \
  -H "Content-Type: application/json" \
  -d '{
    "repo_dir": "/path/to/your/project",
    "source": "HEAD",
    "target": "origin/main",
    "goal": "test"
  }'
# → 202 Accepted, { "run_id": "...", "status": "running" }

# Sonucu poll et
curl http://localhost:8080/api/v1/validations/<run-id>
# → { "status": "success", "affected_modules": [...], "selected_tests": [...], "risk_level": "MEDIUM" }
```

Web UI'da "Local Repo" sekmesi bu endpoint'i doğrudan kullanır.

## Test puanlama sinyalleri

| Sinyal | Ağırlık |
|--------|---------|
| İsim eşleşmesi (OrderService → OrderServiceTest) | 0.40 |
| Direct import | 0.35 |
| Type reference | 0.25 |
| 1-hop ters bağımlılık | 0.20 |
| 2-hop ters bağımlılık | 0.12 |
| 3-hop ters bağımlılık | 0.06 |
| Aynı Maven modülü | 0.10 |
| Aynı package | 0.08 |
| Downstream modülde | 0.05 |
| IT testi (küçük ceza) | -0.05 |
| Git geçmişinde ≥5 birlikte değişmiş | +0.15 |
| Git geçmişinde 2-4 birlikte değişmiş | +0.10 |
| Git geçmişinde 1 kez birlikte değişmiş | +0.05 |

## Mimari

```
mergemate/
  domain/        Tüm domain modelleri
  git/           merge-base diff, geçici worktree yönetimi
  maven/         wrapper, JDK tespiti, proje yükleyici, komut oluşturucu
  impact/        modül grafiği, dosya eşleyici, risk motoru, ImpactAnalyzer
  java_analysis/ Java parser (javalang+regex), class graph, test finder, scorer
  execution/     ExecutionAdapter ABC, LocalWorktreeAdapter, runner
  reporting/     console, JSON, dosya raporu
  config/        .mergemate.yml yükleyici
  cli/           analyze/test/compile/verify CLI komutları

# Opsiyonel Docker katmanı:
forge_worker/    git guard, lifecycle, Dockerfile
forge_orchestrator/  Worker, Orchestrator, reaper
forge_api/       FastAPI REST API + SQLite
forge_spi/       ValidationStep ABC + plugin'ler
forge_analysis/  FailureAnalyzer
web/             React + Vite + TypeScript dashboard
```

## Testler

```bash
# Tüm testler
py -m pytest tests/ -v

# Sadece entegrasyon testleri (gerçek git gerektirir)
py -m pytest tests/ -v -m integration
```

**483 test, tümü geçiyor.**

| Faz / Özellik | İçerik | Testler |
|---------------|--------|---------|
| Faz 1 | Domain, Git diff, Worktree, JDK, CLI | 43 |
| Faz 2 | Maven proje, modül grafiği, etki analizi, risk, raporlama | 36 |
| Faz 3 | Java source parser, class graph, test finder, test scorer | 31 |
| Faz 4 | Komut oluşturucu, runner, rapor dosyası, E2E testi | 42 |
| Faz 5 | Docker adapter, FastAPI async, lifecycle fix | 59 |
| HTML rapor + Surefire | `report.html` + Surefire/Failsafe XML parser | 43 |
| API entegrasyonu | `/api/v1/analyze` + impact_data SQLite kalıcılığı | 16 |
| Co-change analizi | Git geçmişinden test puanlama sinyali | 22 |
| Slice 1-7 | forge_* paketleri (Docker tabanlı altyapı) | 191 |

E2E testleri (`tests/test_e2e.py`): gerçek git repo + POM parse + ImpactAnalyzer — Maven kurulumu **gerekmez**.

## Docker modu (opsiyonel)

```bash
docker build -t mergemate-worker:latest forge_worker/
python -m forge_api.main   # → http://localhost:8080
cd web && npm install && npm run dev   # → http://localhost:5173
```
