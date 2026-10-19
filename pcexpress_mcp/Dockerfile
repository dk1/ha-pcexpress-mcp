FROM python:3.12-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app

# Upstream FireBall1725/pcexpress-mcp-server @ 1b131c91bdcabeaee317c70e937592878d201668,
# vendored with patches/0001-require-bearer-on-messages.patch already applied.
# app/login_pcid.py is upstream's login helper, used by the sign-in page.
COPY app/requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt
COPY app/ /app/
COPY signin_page.py /app/signin_page.py
COPY run.py /run.py

CMD ["python3", "/run.py"]
