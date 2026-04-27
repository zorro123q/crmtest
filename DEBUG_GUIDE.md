# SalesPilot CRM 手机和网页联调指南

## 1. 适用范围

这个仓库目前是两部分：

- `frontend/`: 纯静态 HTML 页面，通过 `frontend/serve.js` 启动本地静态服务，默认端口 `3000`
- `backend/`: FastAPI 后端，通过 `backend/main.py` 启动，默认端口 `8000`

没有单独的原生 App 目录，所以“手机联调”指的是手机浏览器访问前端页面，并联通 PC 上启动的后端接口。

## 2. 页面和接口的关系

可以先按下面的方式理解项目：

| 页面 | 主要用途 | 是否依赖后端 |
| --- | --- | --- |
| `frontend/index.html` | 入口页/导航页 | 否，纯展示可单独预览 |
| `frontend/page-metadata.html` | 元数据展示页 | 否，纯展示可单独预览 |
| `frontend/login.html` | 登录页 | 是，调用 `/api/auth/login` |
| `frontend/crm-system.html`、`frontend/page-*.html`、`frontend/admin-users.html` | CRM 桌面页 | 是 |
| `frontend/ai-input.html` | 手机录入页 | 是，依赖登录、AI 解析、语音转写 |
| `frontend/card-input.html` | 手机评分页 | 是，调用 `/api/card-evaluations/*` |

对应的后端接口入口：

- 登录和鉴权：`/api/auth/*`
- 线索：`/api/leads`
- 商机：`/api/opportunities`
- AI 录入：`/api/ai/parse`、`/api/ai/transcribe`
- 卡片评分：`/api/card-evaluations/evaluate`、`/api/card-evaluations/transcribe`

## 3. 联调前准备

至少确认这几项：

- 电脑和手机在同一个局域网
- Windows 防火墙允许访问 `3000` 和 `8000`
- 后端数据库可用
- 如果要测 AI 解析，`OPENAI_API_KEY` 已配置
- 如果要测语音转写，`DASHSCOPE_API_KEY` 已配置

后端的必填配置来自 `backend/.env`。仓库里已经有模板 `backend/.env.example`。

### 3.1 如果你使用 conda

`conda` 只负责 Python 解释器和依赖环境，不替代项目自己的业务配置。

这意味着：

- 你可以用 conda 来启动后端
- 但后端仍然需要拿到 `DATABASE_URL`、`DATABASE_SYNC_URL`、`SECRET_KEY`
- 这些值可以放在 `backend/.env`
- 也可以不建 `.env`，直接在激活后的 conda 终端里通过环境变量提供

推荐先激活你的 conda 环境：

```powershell
conda activate 你的环境名
```

然后安装后端依赖：

```powershell
pip install -r backend/requirements.txt
```

前端这部分不是 Python，不受 conda 直接管理，仍然需要 `node` 和 `npm`。

如果你电脑里已经装了 Node.js，直接用就行；如果你想也放进 conda 环境里，可以安装：

```powershell
conda install -c conda-forge nodejs
```

## 4. 后端启动

### 4.1 配置 `.env`

在 `backend/` 目录下，把 `.env.example` 复制成 `.env`，至少补齐这些值：

```env
DATABASE_URL=mysql+aiomysql://user:password@127.0.0.1:3306/salespilot_db
DATABASE_SYNC_URL=mysql+pymysql://user:password@127.0.0.1:3306/salespilot_db
SECRET_KEY=replace-with-your-own-secret
```

如果要做手机联调，`CORS_ORIGINS` 里至少加入你电脑的局域网地址来源，例如：

```env
CORS_ORIGINS=["http://localhost:3000","http://127.0.0.1:3000","http://192.168.1.23:3000"]
```

注意这里填的是前端页面来源，不是 API 地址。手机从 `http://192.168.1.23:3000` 打开页面时，后端必须放行这个来源。

如果你要调 AI 页，再补：

```env
OPENAI_API_KEY=sk-...
DASHSCOPE_API_KEY=...
```

说明：

- `ai-input.html` 的文本解析依赖 `OPENAI_API_KEY`
- `ai-input.html` 的语音转写依赖 `DASHSCOPE_API_KEY`
- `card-input.html` 的评分接口是本地规则计算，不依赖 OpenAI；但它的语音转写仍依赖 `DASHSCOPE_API_KEY`

### 4.1.1 `.env` 字段说明

下面这些字段是当前项目里最核心的后端配置。

`DATABASE_URL`

- 用途：后端异步数据库连接，FastAPI 正常启动和接口读写都靠它
- 当前格式：`mysql+aiomysql://用户名:密码@主机:端口/数据库名`
- 你的示例表示：使用 `salespilot` 用户连接本机 `127.0.0.1:3306` 上的 `salespilot_db`
- 是否必填：是

`DATABASE_SYNC_URL`

- 用途：同步版数据库连接串，通常给同步脚本、迁移工具或以后扩展使用
- 当前格式：`mysql+pymysql://用户名:密码@主机:端口/数据库名`
- 是否必填：是
- 说明：当前仓库主流程主要走异步连接，但配置层把它定义成必填，所以仍然要配，建议和 `DATABASE_URL` 指向同一个库

`SECRET_KEY`

- 用途：JWT 登录 token 的签名密钥
- 是否必填：是
- 影响：如果这个值变了，之前签发的 token 会全部失效，需要重新登录
- 建议：本地开发可以自定义一个固定值，生产环境不要用简单明文

`ALGORITHM`

- 用途：JWT 签名算法
- 当前项目支持：`HS256`、`HS384`、`HS512`
- 是否必填：否，默认就是 `HS256`
- 建议：保持 `HS256` 即可，不需要随便改

`ACCESS_TOKEN_EXPIRE_MINUTES`

- 用途：登录 token 过期时间，单位是分钟
- 你的值 `480` 表示：8 小时
- 是否必填：否
- 建议：本地联调保留 `480` 没问题

`OPENAI_API_KEY`

- 用途：`/api/ai/parse` 文本结构化解析时调用 OpenAI
- 是否必填：只有在使用 `ai-input.html` 的 AI 文本解析时才必填
- 注意：像 `sk-temp-placeholder` 这种占位值不能真实调用接口

`OPENAI_MODEL`

- 用途：指定文本解析使用的 OpenAI 模型
- 你的值：`gpt-4o`
- 是否必填：否
- 建议：当前代码默认就是 `gpt-4o`，不改也可以

`DASHSCOPE_API_KEY`

- 用途：语音转写接口调用阿里 DashScope 的 paraformer
- 是否必填：只要测语音转写就必填
- 影响页面：`ai-input.html` 和 `card-input.html` 的录音转写
- 安全建议：这是密钥，不能提交到仓库，也不要出现在截图、聊天记录或共享文档里

`DASHSCOPE_BASE_URL`

- 用途：DashScope 请求的基础地址
- 是否必填：否
- 建议：保持你当前值或使用默认值都可以，核心是和当前转写接口保持一致

`PARAFORMER_MODEL`

- 用途：指定语音转写模型
- 你的值：`paraformer-v2`
- 是否必填：否
- 建议：保持默认即可

`PARAFORMER_LANGUAGE_HINTS`

- 用途：给 paraformer 的语言提示
- 你的值：`["zh","en"]`
- 是否必填：否
- 含义：优先按中文和英文混合场景识别

`APP_NAME`

- 用途：后端服务名称，显示在接口文档和 `/api/health` 返回里
- 是否必填：否
- 建议：保持 `SalesPilot CRM`

`APP_ENV`

- 用途：运行环境标识
- 你的值：`development`
- 是否必填：否
- 影响：当前代码里会影响 SQLAlchemy 是否打印调试 SQL

`CORS_ORIGINS`

- 用途：后端允许哪些前端来源跨域调用
- 是否必填：联调时非常重要
- 格式：JSON 数组字符串，例如 `["http://localhost:3000","http://127.0.0.1:3000"]`
- 关键点：这里填的是前端页面地址，不是后端 API 地址

针对你现在这份配置，`CORS_ORIGINS` 只放行了 `5500` 和 `8080`，但当前项目自带前端服务 `frontend/serve.js` 默认跑在 `3000`，所以如果你用：

```powershell
cd frontend
npm run dev
```

那你至少应该补上：

```env
CORS_ORIGINS=["http://localhost:3000","http://127.0.0.1:3000","http://localhost:5500","http://127.0.0.1:5500","http://localhost:8080","http://127.0.0.1:8080"]
```

如果还要手机联调，再继续补局域网地址，例如：

```env
CORS_ORIGINS=["http://localhost:3000","http://127.0.0.1:3000","http://192.168.1.23:3000"]
```

如果你不想创建 `backend/.env`，也可以在 conda 激活后的 PowerShell 终端里临时设置：

```powershell
conda activate 你的环境名

$env:DATABASE_URL="mysql+aiomysql://user:password@127.0.0.1:3306/salespilot_db"
$env:DATABASE_SYNC_URL="mysql+pymysql://user:password@127.0.0.1:3306/salespilot_db"
$env:SECRET_KEY="replace-with-your-own-secret"
```

如果还要联调 AI，再继续补：

```powershell
$env:OPENAI_API_KEY="sk-..."
$env:DASHSCOPE_API_KEY="..."
```

说明：

- 这种方式只对当前终端生效
- 关闭终端后需要重新设置
- 长期联调还是更推荐 `backend/.env`

### 4.2 初始化数据库

这个仓库当前是 SQL 迁移文件，不是自动 Alembic 流程。首次启动前，按顺序执行：

1. `backend/migrations/001_init_schema.sql`
2. `backend/migrations/002_add_permissions.sql`

执行完以后，创建管理员账号：

```powershell
cd backend
python create_admin.py --email admin@example.com --username admin --password 123456
```

如果数据库里已经有 admin，但密码不确定，可以使用：

```powershell
cd backend
python reset_admin_password.py
```

登录时要注意，后端按 `username` 登录，不是按邮箱登录。

### 4.3 启动后端

如果你使用 conda，先激活 conda 环境；如果你使用普通 venv，再激活 `.venv`。没有装依赖的话先安装：

```powershell
conda activate 你的环境名
cd backend
pip install -r requirements.txt
python main.py
```

后端会监听：

```text
http://0.0.0.0:8000
```

本机验证：

- 健康检查：`http://127.0.0.1:8000/api/health`
- 接口文档：`http://127.0.0.1:8000/api/docs`

## 5. 前端启动

前端没有构建步骤，本质上就是启动静态文件服务。

### 5.1 只在电脑本机预览

```powershell
conda activate 你的环境名
cd frontend
npm run dev
```

默认监听：

```text
http://127.0.0.1:3000
```

### 5.2 让手机也能访问

`frontend/serve.js` 默认只绑定 `127.0.0.1`，所以手机访问前必须改成监听所有网卡：

```powershell
conda activate 你的环境名
cd frontend
$env:HOST="0.0.0.0"
$env:PORT="3000"
npm run dev
```

然后在电脑上执行：

```powershell
ipconfig
```

找到当前网卡的 IPv4，比如 `192.168.1.23`。

这时：

- 电脑访问：`http://127.0.0.1:3000`
- 手机访问：`http://192.168.1.23:3000`

如果手机打不开，多半是下面几类问题：

- 前端没有用 `HOST=0.0.0.0` 启动
- 电脑和手机不在同一局域网
- Windows 防火墙拦截了 `3000`

## 6. 这个项目最关键的地址规则

这部分是整个联调里最容易踩坑的地方。

### 6.1 `login.html` 和 `crm-common.js` 页

`login.html`、`ai-input.html`、`crm-system.html`、`page-*.html` 这一组页面走的是 `crm-common.js` 逻辑。

它们的 API 地址规则是：

1. 先读 `localStorage.crm_api_base`
2. 如果没有，再看是否是 `localhost/127.0.0.1`
3. 否则默认用当前页面的 `window.location.origin`

这意味着：

- 页面从 `http://127.0.0.1:3000` 打开时，如果没配置，会默认把 API 指到 `http://127.0.0.1:8000`
- 页面从 `http://192.168.1.23:3000` 打开时，如果没配置，会错误地把 API 指到 `http://192.168.1.23:3000`

所以手机联调时，必须显式指定后端地址。

最稳妥的打开方式：

```text
http://192.168.1.23:3000/login.html?apiBase=http://192.168.1.23:8000
```

登录成功后，`login.html` 会把这个值写入：

```text
localStorage.crm_api_base
```

后续页面就会继续使用这个 API 地址。

如果你不想走登录页，也可以在浏览器控制台手动写入：

```js
localStorage.setItem('crm_api_base', 'http://192.168.1.23:8000')
```

### 6.2 `card-input.html` 的规则和别的页面不一样

`card-input.html` 没有走 `crm-common.js`，它自己拼地址：

- 当页面端口是 `3000/5173/5500/5501/8080` 时
- 它会自动请求 `http://当前页面主机名:8000/api/...`

也就是说：

- 电脑打开 `http://127.0.0.1:3000/card-input.html`，它会请求 `http://127.0.0.1:8000/api/card-evaluations/...`
- 手机打开 `http://192.168.1.23:3000/card-input.html`，它会请求 `http://192.168.1.23:8000/api/card-evaluations/...`

这一页不依赖 `crm_api_base`，但仍然依赖：

- 后端 `8000` 已启动
- 后端 CORS 放行 `http://192.168.1.23:3000`
- 手机能访问电脑的 `8000` 端口

## 7. 推荐联调顺序

### 场景 A：只看页面样式

适合先做手机和网页 UI 对齐。

1. 启动前端静态服务
2. 电脑打开 `index.html`、`page-metadata.html`
3. 手机打开同一页面的局域网地址
4. 对比布局、换行、滚动、触控区、字体和安全区

这个阶段可以不启动后端。

### 场景 B：桌面页和手机页一起调接口

这是最常用的完整联调流程。

1. 启动 MySQL
2. 确认 `backend/.env` 已配置好数据库、`SECRET_KEY`、`CORS_ORIGINS`
3. 启动后端 `python main.py`
4. 本机先打开 `http://127.0.0.1:8000/api/health`
5. 前端用 `HOST=0.0.0.0` 启动
6. 电脑打开 `http://127.0.0.1:3000/login.html?apiBase=http://127.0.0.1:8000`
7. 手机打开 `http://192.168.1.23:3000/login.html?apiBase=http://192.168.1.23:8000`
8. 用管理员用户名登录
9. 电脑端调桌面页，手机端调 `ai-input.html` 或 `card-input.html`

### 场景 C：只调手机录音和 AI

1. 后端启动
2. `OPENAI_API_KEY`、`DASHSCOPE_API_KEY` 已配置
3. 手机打开 `ai-input.html` 或 `card-input.html`
4. 首次录音时允许麦克风权限
5. 在浏览器开发者工具里同时看 `Network` 和 `Console`

## 8. 常见问题排查

### 8.1 手机能打开页面，但接口请求失败

优先检查：

- `crm_api_base` 是否已经写成 `http://电脑IP:8000`
- 后端是否已经把 `http://电脑IP:3000` 加到 `CORS_ORIGINS`
- 后端是否已经重启

### 8.2 手机打不开页面

优先检查：

- 前端是否用 `HOST=0.0.0.0` 启动
- 电脑 `ipconfig` 里的 IPv4 是否写对
- 电脑防火墙是否放行 `3000`

### 8.3 手机能打开 `card-input.html`，但评分或转写失败

优先检查：

- 后端 `8000` 是否真的可访问
- `card-input.html` 请求的是不是 `http://电脑IP:8000/api/card-evaluations/...`
- 如果是转写失败，重点看 `DASHSCOPE_API_KEY`

### 8.4 `ai-input.html` 登录后仍然报 401

优先检查：

- 是否先通过 `login.html` 登录
- `localStorage.crm_token` 是否存在
- 当前用户是否有对应权限

### 8.5 AI 解析返回 502

优先检查：

- `OPENAI_API_KEY` 是否配置
- `DASHSCOPE_API_KEY` 是否配置
- 外网访问是否正常

### 8.6 双击 HTML 文件直接打开后异常

`card-input.html` 明确不支持 `file://` 直接打开，必须通过 HTTP 静态服务访问。其他页面联调时也建议统一走 `npm run dev`。

### 8.7 登录时报错 `Unknown column 'users.permissions'`

如果你看到类似报错：

```text
Unknown column 'users.permissions' in 'field list'
```

说明代码已经升级到带权限字段的版本，但数据库还停留在旧表结构。

根因：

- `backend/app/models/__init__.py` 里的 `User` 模型包含 `permissions`
- 但你的数据库没有执行 `backend/migrations/002_add_permissions.sql`

修复方式二选一。

方式 1：直接执行迁移 SQL

```sql
ALTER TABLE users ADD COLUMN permissions JSON NULL DEFAULT NULL AFTER is_active;
```

方式 2：运行仓库里的幂等修复脚本

```powershell
cd backend
python repair_users_permissions_column.py
```

这个脚本会先检查字段是否存在：

- 已存在就跳过
- 不存在才补列

修复完成后重试登录即可。

## 9. 最短可执行方案

如果你只想按最短路径把整套联调跑起来，直接照着做：

```powershell
# 终端 1
conda activate 你的环境名
cd backend
pip install -r requirements.txt
python main.py
```

```powershell
# 终端 2
conda activate 你的环境名
cd frontend
$env:HOST="0.0.0.0"
$env:PORT="3000"
npm run dev
```

如果你没有使用 `backend/.env`，就在终端 1 里先补这些变量再启动后端：

```powershell
$env:DATABASE_URL="mysql+aiomysql://user:password@127.0.0.1:3306/salespilot_db"
$env:DATABASE_SYNC_URL="mysql+pymysql://user:password@127.0.0.1:3306/salespilot_db"
$env:SECRET_KEY="replace-with-your-own-secret"
```

然后：

1. 电脑访问 `http://127.0.0.1:3000/login.html?apiBase=http://127.0.0.1:8000`
2. 手机访问 `http://电脑IPv4:3000/login.html?apiBase=http://电脑IPv4:8000`
3. 后端 `.env` 里的 `CORS_ORIGINS` 确保包含 `http://电脑IPv4:3000`
4. 用 `username` 登录

这套流程可以覆盖桌面页、手机页和后端接口联调。
