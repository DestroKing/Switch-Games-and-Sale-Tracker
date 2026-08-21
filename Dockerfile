# Everything the tracker needs, sealed in one image: Bun, Playwright and
# Chromium. Nothing lands on the host except Docker itself and the SQLite file.

FROM oven/bun:1-debian

# Chromium's system libraries need apt, which needs root. The oven/bun images
# drop to an unprivileged user by default.
USER root
WORKDIR /app

# Dependencies first, as their own layer — this way a code edit doesn't force a
# 300 MB browser re-download on every rebuild.
COPY package.json ./
RUN bun install

# --with-deps pulls the shared libraries headless Chromium needs on Debian.
# Skipping this is the usual cause of "browser closed unexpectedly" in a container.
RUN bunx playwright install --with-deps chromium

COPY . .

# The SQLite file lives here. Mounted as a volume so the history outlives the
# container, which is the whole point of collecting it.
VOLUME ["/app/data"]
ENV TRACKER_DB=/app/data/tracker.db

# Play-Asia and Amazon serve different pages by locale. Ask for India.
ENV TZ=Asia/Kolkata
ENV LANG=en_IN.UTF-8

ENTRYPOINT ["bun", "run", "src/index.ts"]
CMD ["collect"]
