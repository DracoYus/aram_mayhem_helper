FROM python:3.12-slim

ENV PIP_INDEX_URL=https://pypi.tuna.tsinghua.edu.cn/simple
ENV PIP_TRUSTED_HOST=pypi.tuna.tsinghua.edu.cn
# 关闭pip本地缓存（配合--no-cache-dir进一步减小镜像）
ENV PIP_NO_CACHE_DIR=1

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app.py .

EXPOSE 5000

# 提醒：运行时需挂载宿主机的 data 目录到 /app/data
VOLUME ["/app/data"]

CMD ["python", "app.py"]
