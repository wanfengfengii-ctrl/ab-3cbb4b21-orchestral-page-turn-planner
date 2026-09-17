# 排练翻页规划（Page-Turn Planner）

为排练中的管弦乐手规划乐谱分页：把 1–500 个连续小节分配到容量固定的页面上，
让每次翻页都尽量落在足够长的休止之后；当多种排法同样优秀时，给出可复算的唯一结果。

技术栈：React + TypeScript（Vite）前端 · FastAPI 后端 · 自实现动态规划 ·
Docker Compose 一键启动（web / api / 一次性 verify）。

## 快速开始

```bash
docker compose up --build -d web api
```

- 前端：http://localhost:${WEB_PORT:-8080}
- API：http://localhost:${API_PORT:-8000}（文档见 `/docs`）

宿主端口可用环境变量覆盖：

```bash
WEB_PORT=9000 API_PORT=9001 docker compose up --build -d web api
```

运行一次性端到端校验（对照独立暴力枚举验证 DP 最优性、422 校验规则、web 服务）：

```bash
docker compose up --build --exit-code-from verify verify
```

verify 全部通过时以退出码 0 结束，否则为 1 并列出失败项。

## 问题定义与优化目标

每个小节只有 `height`（占用高度）与 `restAfterMs`（小节后的休止毫秒）。
一种方案把小节序列切分为连续页面，每页高度之和不得超过 `pageCapacity`。
除末页外，每页末尾都要翻页：该页末小节的 `restAfterMs >= turnRequiredMs`
视为**安全**，否则为**不安全**，缺口为 `turnRequiredMs - restAfterMs`。

合法方案按以下目标**依次**最小化（字典序）：

1. 页数；
2. 不安全翻页数；
3. 最大休止缺口（仅统计不安全的非末页，没有此类页时为 0）；
4. 各页剩余容量的平方和（含末页）。

仍并列时，比较由各非末页末小节的 1 基序号组成的序列，取字典序最小者。
因此结果唯一、可复算。后端用动态规划求解（`api/app/planner.py`），
复杂度 O(n²)，n ≤ 500。

## API

### `POST /api/plan`

```json
{
  "pageCapacity": 300,
  "turnRequiredMs": 500,
  "measures": [
    { "height": 42, "restAfterMs": 0 },
    { "height": 38, "restAfterMs": 900 }
  ]
}
```

**200 响应**：分页点、完整目标向量与逐页明细。

```json
{
  "pageCapacity": 300,
  "turnRequiredMs": 500,
  "objective": { "pages": 1, "unsafeTurns": 0, "maxGapMs": 0, "slackSquares": 48400 },
  "breaks": [],
  "pages": [
    {
      "index": 1, "start": 1, "end": 2,
      "heightSum": 80, "remaining": 220,
      "turn": null
    }
  ]
}
```

- `breaks`：各非末页末小节的 1 基序号（分页点）。
- `objective`：按上述顺序排列的完整目标向量
  （`pages` → `unsafeTurns` → `maxGapMs` → `slackSquares`）。
- `pages[].turn`：非末页为 `{ "safe", "restAfterMs", "gapMs" }`（安全时 `gapMs` 为 0）；
  末页为 `null`（不翻页，不参与安全性与缺口统计）。

### 输入校验（任一非法即整批 422）

- 所有数值必须是**词法匹配 `0|[1-9]\d*` 的 JSON 数字**：拒绝小数、指数、
  字符串、布尔、空值、负数和前导零（前导零本身即非法 JSON）。
- `height`、`pageCapacity`：1–30000；`restAfterMs`、`turnRequiredMs`：0–30000。
- 每个小节的 `height` 不得超过 `pageCapacity`。
- `measures` 为 1–500 个对象，每个对象仅含 `height`、`restAfterMs`；
  顶层仅含 `pageCapacity`、`turnRequiredMs`、`measures`；拒绝重复键。

**422 响应**：`errors` 数组按输入位置稳定排列，前端收到后清除旧方案。

```json
{
  "errors": [
    { "path": "pageCapacity", "message": "must be between 1 and 30000" },
    { "path": "measures[0].restAfterMs", "message": "must be a JSON number, not a string" }
  ]
}
```

另有 `GET /api/health` 供健康检查。

## 本地开发（不用 Docker）

```bash
# API（http://localhost:8000）
cd api
pip install -r requirements.txt
uvicorn app.main:app --reload

# 前端（http://localhost:5173，/api 自动代理到 8000 端口）
cd web
npm install
npm run dev
```

前端开发代理目标可用 `API_PROXY_TARGET` 环境变量覆盖。

## 目录结构

```
├── docker-compose.yml      # web / api / verify 三个服务，WEB_PORT、API_PORT 可覆盖
├── api/                    # FastAPI：严格校验 + 动态规划
│   └── app/{main,planner,validation}.py
├── web/                    # React + TypeScript（Vite），nginx 反代 /api
│   └── src/{App.tsx,main.tsx,styles.css}
└── verify/                 # 一次性校验服务：暴力枚举对照 + 422 规则 + web 检查
    └── verify.py
```
