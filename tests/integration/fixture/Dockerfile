FROM python:3-alpine
ARG BUILD_ID
LABEL lima-ai-test.build-id=$BUILD_ID
RUN mkdir -p /data && echo empty > /data/index.html
CMD ["python", "-m", "http.server", "8002", "--directory", "/data"]
