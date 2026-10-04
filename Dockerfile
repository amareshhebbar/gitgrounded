FROM python:3.12-slim
RUN apt-get update && apt-get install -y --no-install-recommends git && rm -rf /var/lib/apt/lists/*
COPY . /src
RUN pip install --no-cache-dir "/src[sign,mcp]" && rm -rf /src
WORKDIR /work
ENTRYPOINT ["gitgrounded"]
CMD ["--help"]
