FROM python:3.13-slim
WORKDIR /reader
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY app ./app
RUN useradd --uid 10001 --create-home reader && mkdir /data && chown reader:reader /data
USER reader
ENV RESEARCHDOCK_CLOUD_DATA=/data
EXPOSE 8080
CMD ["python","-m","uvicorn","app.mobile_cloud:app","--host","0.0.0.0","--port","8080","--no-access-log"]
