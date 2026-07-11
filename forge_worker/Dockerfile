# forge_worker/Dockerfile
#
# Hardened worker image for MergeMate validation runs.
# Base: eclipse-temurin:17-jdk-jammy (LTS JDK on Ubuntu 22.04)
#
# Security posture:
#   - Non-root user 'worker' (uid 1001, gid 1001)
#   - No sudo
#   - git safe.directory set to the work dir
#   - Maven .m2 cache owned by worker
#   - Minimal installed packages

FROM eclipse-temurin:17-jdk-jammy

# ---------------------------------------------------------------------------
# 1. Install Maven and git in a single layer; clean up apt caches.
# ---------------------------------------------------------------------------
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        git \
        maven \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

# ---------------------------------------------------------------------------
# 2. Create non-root user 'worker' (uid 1001, gid 1001).
# ---------------------------------------------------------------------------
RUN groupadd --gid 1001 worker \
    && useradd --uid 1001 --gid worker --shell /bin/bash --create-home worker

# ---------------------------------------------------------------------------
# 3. Create the work directory and set ownership.
# ---------------------------------------------------------------------------
RUN mkdir -p /work/repo \
    && chown -R worker:worker /work

# ---------------------------------------------------------------------------
# 4. Pre-create the Maven .m2 cache directory, owned by worker.
# ---------------------------------------------------------------------------
RUN mkdir -p /home/worker/.m2/repository \
    && chown -R worker:worker /home/worker/.m2

# ---------------------------------------------------------------------------
# 5. Configure git safe.directory so worker can operate on /work/repo
#    even if the directory was created by root.
# ---------------------------------------------------------------------------
RUN git config --system safe.directory /work/repo

# ---------------------------------------------------------------------------
# 6. Copy the forge_worker package into the image.
# ---------------------------------------------------------------------------
COPY --chown=worker:worker forge_worker/ /app/forge_worker/

# ---------------------------------------------------------------------------
# 7. Environment / paths.
# ---------------------------------------------------------------------------
ENV HOME=/home/worker \
    MAVEN_OPTS="-Xms256m -Xmx1g" \
    PATH="/usr/share/maven/bin:${PATH}"

WORKDIR /work

# ---------------------------------------------------------------------------
# 8. Drop to non-root user for all subsequent operations.
# ---------------------------------------------------------------------------
USER worker

# ---------------------------------------------------------------------------
# 9. Entrypoint: /bin/bash (orchestrator will exec commands in).
# ---------------------------------------------------------------------------
ENTRYPOINT ["/bin/bash"]
