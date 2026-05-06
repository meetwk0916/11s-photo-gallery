# 11去哪玩 MVP

这个仓库现在落地的是一个可本地跑通的 MVP：把照片导入进来，按旅程线索自动归类，并生成待发送的小红书图文草稿。Google Drive / Google Photos Takeout 保留为可选增强，默认推荐先走本地上传模式把流程跑通。

## 当前能力

- 本地上传照片，自动按文件名中的日期和主题词归类为旅程
- 生成 `11去哪玩` 风格的小红书草稿，并提供手机预览
- 无 API key 时使用内置旅行模板，保证 MVP 可演示
- 无 Google token 时自动降级到本地模式，不阻塞主流程
- 导出草稿到本地 `data/exports/`；配置好 Google OAuth 后可导出到 Drive

## 已验证的本地闭环

在当前 Linux 环境中，以下链路已经验证通过：

1. 启动 Flask 服务
2. 本地上传图片到 `/api/local-photos`
3. 自动生成旅程标签，如 `11去哪玩 | 04/01 城市漫游`
4. 调用 `/api/generate` 生成小红书文案
5. 调用 `/api/export/<id>` 导出到 `data/exports/`

## 快速启动

### 1. 启动服务

```bash
cd /home/meetwk0916/projects/11s-photo-gallery
chmod +x run.sh
./run.sh foreground
```

默认打开：`http://localhost:5000`

### 2. 如果系统没有 `python3-venv`

这台 Debian/Ubuntu 机器常见的阻塞是 `python3 -m venv` 无法使用。推荐二选一：

```bash
# 方案 A：有 sudo 时
sudo apt install python3.12-venv
```

```bash
# 方案 B：无 sudo 时，用用户目录 bootstrap virtualenv
curl -fsSL https://bootstrap.pypa.io/get-pip.py -o /tmp/get-pip.py
python3 /tmp/get-pip.py --user --break-system-packages
~/.local/bin/pip install --user --break-system-packages virtualenv
```

完成后重新执行 `./run.sh foreground`。

### 3. 使用本地 MVP

1. 打开页面
2. 点击 `上传本地照片`
3. 可选填写旅程名称，例如 `清明杭州两日游`
4. 选择一张旅程卡片
5. 点击 `生成内容`
6. 在右侧预览和编辑后点击 `导出到本地`

导出的 Markdown 位于 `data/exports/`。

## 可选增强

### AI Provider

配置任意一个即可启用真实多模态生成：

```bash
export ANTHROPIC_API_KEY="sk-..."
# 或
export OPENAI_API_KEY="sk-..."
# 或
export GEMINI_API_KEY="..."
```

### Google Drive / Google Photos Takeout

如果你已经配置过 Google OAuth，并且本地存在：

```bash
~/.hermes/google_token.json
```

那么可以使用：

- Drive watcher
- Drive 导出
- Takeout ZIP 同步

## 关键接口

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/status` | GET | 查看当前是本地 MVP 还是 Drive 模式 |
| `/api/local-photos` | POST | 上传本地照片并自动归类旅程 |
| `/api/posts` | GET | 获取当前旅程队列 |
| `/api/generate` | POST | 为旅程生成小红书等平台内容 |
| `/api/update-content` | POST | 编辑草稿 |
| `/api/export/<id>` | POST | 导出到本地或 Drive |

## 当前已知设计取舍

- 旅程归类目前基于文件名中的日期和关键词，是启发式规则，不是 EXIF/地理信息级别的精确聚类
- 无 AI key 时使用模板回退，保证演示流畅，但内容质量不如真实视觉模型
- Google Photos 仍然是可选增强，不再是默认必需依赖

## 下一步建议

1. 增加 EXIF 解析，用拍摄时间和地理位置替代文件名启发式
2. 支持一个旅程多图轮播预览，而不是只展示封面图
3. 针对 `11去哪玩` 增加路线推荐、预算、交通、最佳出片时间等结构化字段
