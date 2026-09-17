# 管弦乐翻页编排（Orchestra Page-Turn Planner）

为排练中的管弦乐手计算最优分页方案：把 1–500 个连续小节划分成若干页，使翻页
尽量发生在休止足够长、可以从容翻页的位置。所有目标相同的方案中，结果是可复算
的唯一解。

- **web**：React + TypeScript 表单，编辑小节、提交求解、展示分页与翻页安全性
- **api**：FastAPI 服务，负责严格校验与动态规划求解
- **verify**：一次性端到端校验容器，对求解器做穷举对照、跑完全部校验规则

## 快速开始

```bash
docker compose up --build
```

| 服务 | 默认宿主端口 | 覆盖方式 |
| ---- | ------------ | -------- |
| web  | 8081         | `WEB_PORT=9000 docker compose up --build` |
| api  | 8080         | `API_PORT=9001 docker compose up --build` |

打开 <http://localhost:8081> 即可使用；前端通过 nginx 将 `/api/*` 代理到 api 服务。

运行一次性端到端校验（穷举对照 + 校验规则 + web 代理检查）：

```bash
docker compose up --build -d        # 先启动 web 与 api
docker compose run --rm verify      # 退出码 0 表示全部通过
```

## 问题定义

每个小节只有两个属性：`height`（占用高度）与 `restAfterMs`（小节后的休止时长）。
全局参数为 `pageCapacity`（每页容量）与 `turnRequiredMs`（从容翻页所需的休止阈值）。

把小节序列切分成连续区间（页），每页高度和不得超过 `pageCapacity`。候选方案按
以下目标向量做字典序比较，取最小者：

1. **页数** `pages` —— 越少越好；
2. **不安全翻页数** `unsafeTurns` —— 非末页的末小节 `restAfterMs < turnRequiredMs`
   即为不安全（末页不翻页，不参与安全性与缺口统计）；
3. **最大休止缺口** `maxGapMs` —— 仅对不安全的非末页计算
   `turnRequiredMs - restAfterMs`，取最大值；没有此类页时为 0；
4. **剩余容量平方和** `sumSquaredSlack` —— 所有页（含末页）的
   `(pageCapacity - 页内高度和)²` 之和；
5. **翻页点序列** `turnPoints` —— 各非末页末小节的一基序号组成的序列，仍并列时
   取字典序最小者。

### 算法

`api/app/solver.py` 中的两阶段动态规划（n ≤ 500 时为毫秒级）：

- **阶段 A**：最小化 `(pages, unsafeTurns, maxGapMs)`。`maxGapMs` 以 `max` 合并而
  非加和，若与更靠后的分量放在同一个字典序 DP 里，最优子结构会被破坏（前缀缺口
  较差但平方和更优时，后续页面的缺口可能拉平最大值），因此瓶颈分量单独成阶段。
- **阶段 B**：把所有非末页的缺口上限固定为阶段 A 的最优值，重跑 DP，最小化
  `(pages, unsafeTurns, sumSquaredSlack, turnPointCode)` —— 全部为加和分量，字典
  序 DP 精确。翻页点序列编码为 `n+1` 进制整数（高位为靠前的翻页点），整数比较即
  等长序列的字典序比较。

## API

### `POST /api/solve`

请求体（所有数值必须是词法匹配 `0|[1-9]\d*` 的 JSON 数字）：

```json
{
  "pageCapacity": 10,
  "turnRequiredMs": 500,
  "measures": [
    {"height": 3, "restAfterMs": 1000},
    {"height": 3, "restAfterMs": 1000},
    {"height": 4, "restAfterMs": 1000},
    {"height": 3, "restAfterMs": 1000},
    {"height": 3, "restAfterMs": 1000}
  ]
}
```

约束：

| 字段 | 范围 |
| ---- | ---- |
| `measures` | 1–500 个对象，每个仅含 `height` 与 `restAfterMs` |
| `height` | 1–30000，且不得超过 `pageCapacity` |
| `pageCapacity` | 1–30000 |
| `restAfterMs` / `turnRequiredMs` | 0–30000 |

小数、指数、字符串、布尔、`null`、负数和前导零一律拒绝。

`200 OK` 响应（分页点、完整目标向量、逐页明细）：

```json
{
  "objective": {"pages": 2, "unsafeTurns": 0, "maxGapMs": 0, "sumSquaredSlack": 16},
  "turnPoints": [2],
  "pageEndIndices": [2, 5],
  "pages": [
    {"page": 1, "startMeasure": 1, "endMeasure": 2, "measureCount": 2,
     "usedHeight": 6, "remainingCapacity": 4, "isLastPage": false,
     "turn": {"restAfterMs": 1000, "requiredMs": 500, "safe": true, "gapMs": 0}},
    {"page": 2, "startMeasure": 3, "endMeasure": 5, "measureCount": 3,
     "usedHeight": 10, "remainingCapacity": 0, "isLastPage": true, "turn": null}
  ]
}
```

任一输入非法时整批返回 `422`，并携带按输入位置稳定排列的全部错误
（`pageCapacity` → `turnRequiredMs` → `measures` → 各小节的 `height`、
`restAfterMs`）；前端收到后会清除旧方案：

```json
{
  "detail": "validation failed",
  "errors": [
    {"path": "pageCapacity", "message": "must be between 1 and 30000"},
    {"path": "measures[0].height", "message": "must be a JSON integer matching 0|[1-9]\\d* (decimals, exponents, strings, booleans and null are rejected)"}
  ]
}
```

另有 `GET /api/health` 用于健康检查。

## 本地开发

```bash
# API（Python 3.11+）
cd api
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
.venv/bin/uvicorn app.main:app --reload --port 8080
.venv/bin/python -m pytest        # 单元测试：DP 对穷举、校验规则

# 前端（Node 20+），dev server 已把 /api 代理到 localhost:8080
cd web
npm install
npm run dev
npm run build                     # tsc 类型检查 + 产物构建

# 端到端校验（需 API 已启动）
cd verify
pip install httpx
API_URL=http://localhost:8080 WEB_URL= python verify.py
```

## 目录结构

```
├── docker-compose.yml      # web / api / verify 三个服务，WEB_PORT、API_PORT 可覆盖
├── api/
│   ├── app/
│   │   ├── main.py         # FastAPI 入口：/api/solve、/api/health
│   │   ├── validation.py   # 词法级 JSON 整数校验，收集全部错误
│   │   └── solver.py       # 两阶段动态规划
│   ├── tests/              # pytest：穷举对照 + API 校验
│   └── Dockerfile
├── web/
│   ├── src/                # React + TypeScript 表单与结果展示
│   ├── nginx.conf          # 静态资源 + /api 反向代理
│   └── Dockerfile
└── verify/
    ├── verify.py           # 一次性端到端校验
    └── Dockerfile
```
