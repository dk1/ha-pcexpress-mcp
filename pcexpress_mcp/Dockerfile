FROM python:3.12-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app

# Upstream FireBall1725/pcexpress-mcp-server, pinned by the upstream/ git submodule.
# Only the files the app runs are copied; login_pcid.py is used by the sign-in page.
COPY upstream/requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt
COPY upstream/pcexpress_mcp_server.py upstream/pcid_token.py upstream/pcid_config.py \
     upstream/version.py upstream/login_pcid.py upstream/LICENSE /app/

# Our changes to upstream, applied in order; the build fails if any patch doesn't apply cleanly.
COPY patches/ /tmp/patches/
RUN apt-get update \
 && apt-get install -y --no-install-recommends patch \
 && for p in /tmp/patches/*.patch; do \
      echo "Applying $p" && patch -p1 --forward --fuzz=0 --no-backup-if-mismatch -d /app < "$p" || exit 1; \
    done \
 && apt-get purge -y --auto-remove patch \
 && rm -rf /var/lib/apt/lists/* /tmp/patches

# Our own files.
COPY signin_page.py ingress.py /app/
COPY fridge_check/ /app/fridge_check/
COPY run.py /run.py

CMD ["python3", "/run.py"]
