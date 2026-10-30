# syntax=docker/dockerfile:1.7
#
# Layer invalidation graph (each line invalidates everything below it):
#
#   extension-builder ──► vsix (changes every extension edit)
#   node-cli          ──► global claude-code / codex (changes on npm package bumps)
#
#   stage-2 foundation: apt, uv, coder user
#   stage-2 static stacks: office document tools
#   stage-2 locked deps: uv.lock / pyproject.toml
#   stage-2 node COPY from node-cli
#   stage-2 agentsociety2 source + editable install
#   stage-2 vsix COPY  ◄── keep last
#
# BuildKit cache mounts (apt / uv / npm) avoid re-downloading on cache miss.

# ================= Stage 1: Build VSCode extension as vsix =================
FROM node:22 AS extension-builder

WORKDIR /app/extension

RUN npm config set registry https://registry.npmmirror.com \
    && npm install -g @vscode/vsce@4.0.0

COPY ./extension/package.json ./extension/package-lock.json ./
COPY ./extension/package.nls.json ./extension/package.nls.zh-cn.json ./
COPY ./extension/.npmrc ./
RUN --mount=type=cache,target=/root/.npm \
    npm ci

COPY ./extension/tsconfig.json ./extension/webpack.config.js ./
COPY ./extension/src/ ./src/
COPY ./extension/media/ ./media/
COPY ./extension/resources/ ./resources/
COPY ./extension/skills/ ./skills/
COPY ./extension/plugins/ ./plugins/
COPY ./extension/runtime/ ./runtime/
COPY ./extension/.vscodeignore ./
COPY ./extension/NOTICE ./NOTICE
COPY ./extension/README.md ./README.md
COPY ./extension/CHANGELOG.md ./CHANGELOG.md
COPY LICENSE ./LICENSE.txt

# vsce invokes vscode:prepublish itself; running it explicitly would compile
# every webview bundle twice in the same image layer.
RUN vsce package --out /app/extension.vsix

# ================= Stage 1b: Global Claude Code / Codex CLIs =================
# Independent of Python lockfile and agentsociety2 source; shares node:22 base cache
# with extension-builder on the runner.
FROM node:22 AS node-cli

RUN --mount=type=cache,target=/root/.npm \
    npm install -g @anthropic-ai/claude-code@2.1.314 @openai/codex@0.166.0

# ================= Stage 2: Python runtime with extension =================
FROM python:3.12

RUN --mount=type=cache,target=/var/cache/apt,sharing=locked \
    --mount=type=cache,target=/var/lib/apt,sharing=locked \
    set -eux; \
    if [ -f /etc/apt/sources.list.d/debian.sources ]; then \
        sed -i 's|deb.debian.org|mirrors.tuna.tsinghua.edu.cn|g' /etc/apt/sources.list.d/debian.sources; \
    else \
        sed -i 's|deb.debian.org|mirrors.tuna.tsinghua.edu.cn|g' /etc/apt/sources.list; \
    fi; \
    apt-get update; \
    DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
        curl \
        sudo \
        locales \
        texlive-latex-recommended \
        texlive-latex-extra \
        texlive-fonts-recommended \
        texlive-fonts-extra \
        texlive-bibtex-extra \
        latexmk \
        biber \
        pandoc \
        libreoffice \
        poppler-utils \
        tesseract-ocr \
        unzip \
        ripgrep \
        vim

RUN ln -sf /usr/local/bin/python3 /usr/bin/python3 \
    && ln -sf /usr/local/bin/python3-config /usr/bin/python3-config \
    && ( [ -f /usr/local/bin/python3.12 ] && ln -sf /usr/local/bin/python3.12 /usr/bin/python3.12 || true )

WORKDIR /app

COPY --from=ghcr.io/astral-sh/uv:0.13.6 /uv /uvx /usr/local/bin/
RUN ln -sf /usr/local/bin/python3 /usr/local/bin/python
RUN mkdir -p /etc/uv \
    && printf '[[index]]\nurl = "https://mirrors.tuna.tsinghua.edu.cn/pypi/web/simple/"\ndefault = true\n' > /etc/uv/uv.toml

ENV UV_LINK_MODE=copy

RUN mkdir -p /etc/sudoers.d \
    && useradd coder --create-home --shell=/bin/bash --uid=1000 --user-group \
    && echo "coder ALL=(ALL) NOPASSWD:ALL" >>/etc/sudoers.d/nopasswd

ENV LANG=C.UTF-8
ENV LANGUAGE=C.UTF-8
ENV LC_ALL=C.UTF-8

# ---- Static Python tool stacks (independent of uv.lock / AS2 source) ----
# Office skills + paper-toolkit: bumping agentsociety2 must not reinstall these.
RUN --mount=type=cache,target=/root/.cache/uv \
    uv pip install --system --torch-backend=cpu \
        pypdf==6.21.4 \
        pdfplumber==0.11.10 \
        reportlab==5.1.0 \
        pytesseract==0.3.13 \
        pdf2image==1.17.0 \
        pandas==2.3.3 \
        openpyxl==3.1.5 \
        python-pptx==1.0.2 \
        Pillow==13.0.0 \
        python-docx==1.2.0 \
        python-dotenv==1.2.4 \
        docling==2.145.0 \
        torch==2.15.0 \
        torchvision==0.29.2 \
        "easypaper[docling,images]==0.2.4" \
        "paper-toolkit==0.1.2"

# ---- Node.js + Claude Code / Codex (independent of uv.lock / AS2 source) ----
# Copy the Node binary and global package tree only. Do NOT COPY /usr/local/bin/{npm,npx,claude,codex}:
# Docker often materializes those shims as plain files, so relative requires like
# `../lib/cli.js` resolve under /usr/local/lib and break (`Cannot find module '../lib/cli.js'`).
COPY --from=node-cli /usr/local/bin/node /usr/local/bin/node
COPY --from=node-cli /usr/local/lib/node_modules /usr/local/lib/node_modules
RUN set -eux; \
    ln -sfn ../lib/node_modules/npm/bin/npm-cli.js /usr/local/bin/npm; \
    ln -sfn ../lib/node_modules/npm/bin/npx-cli.js /usr/local/bin/npx; \
    node <<'NODE'
const fs = require("fs");
const path = require("path");
for (const name of ["@anthropic-ai/claude-code", "@openai/codex"]) {
  const root = path.join("/usr/local/lib/node_modules", name);
  const pkg = JSON.parse(fs.readFileSync(path.join(root, "package.json"), "utf8"));
  const bins =
    typeof pkg.bin === "string"
      ? { [path.basename(name)]: pkg.bin }
      : pkg.bin;
  if (!bins || typeof bins !== "object") {
    throw new Error(`missing bin field in ${name}`);
  }
  for (const [cmd, rel] of Object.entries(bins)) {
    const target = path.join(root, rel);
    if (!fs.existsSync(target)) {
      throw new Error(`missing bin target ${target}`);
    }
    const link = path.join("/usr/local/bin", cmd);
    fs.rmSync(link, { force: true });
    fs.symlinkSync(path.relative("/usr/local/bin", target), link);
  }
}
NODE

# ---- Locked third-party deps from workspace manifest (uv.lock changes only) ----
COPY pyproject.toml uv.lock ./
COPY packages/agentsociety2/pyproject.toml packages/agentsociety2/pyproject.toml
RUN --mount=type=cache,target=/root/.cache/uv \
    uv export --frozen --no-dev --no-emit-package agentsociety2 \
        --format requirements-txt -o /tmp/reqs.txt \
    && uv pip install --system --no-config --no-deps --require-hashes -r /tmp/reqs.txt \
    && rm /tmp/reqs.txt

# ---- agentsociety2 source (editable, deps already present) ----
COPY README.md LICENSE ./
COPY packages/agentsociety2/ ./packages/agentsociety2/
RUN --mount=type=cache,target=/root/.cache/uv \
    uv pip install --system --no-deps -e ./packages/agentsociety2

# ---- Extension vsix (changes most often among runtime layers) ----
COPY --from=extension-builder /app/extension.vsix /app/extension.vsix

USER coder
WORKDIR /home/coder
