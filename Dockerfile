# ARAM Mayhem Helper 网页应用镜像（安装主包，无需 OCR 依赖）
FROM python:3.12-slim

ENV PIP_INDEX_URL=https://pypi.tuna.tsinghua.edu.cn/simple
ENV PIP_TRUSTED_HOST=pypi.tuna.tsinghua.edu.cn
ENV PIP_NO_CACHE_DIR=1

WORKDIR /app

# 先复制构建清单与源码，再安装（利用层缓存）
COPY pyproject.toml .
COPY src ./src
COPY config ./config
COPY data ./data
RUN pip install --no-cache-dir .

# 安装到 site-packages 后无法用源码相对路径定位仓库，需显式指定数据/配置目录
ENV ARAM_MAYHEM_DATA_DIR=/app/data
ENV ARAM_MAYHEM_CONFIG_DIR=/app/config

EXPOSE 5000
# 运行时挂载宿主机 data 目录以提供爬取数据（含静态翻译文件）
VOLUME ["/app/data"]

CMD ["aram-mayhem-helper", "web", "--host", "0.0.0.0", "--port", "5000"]
