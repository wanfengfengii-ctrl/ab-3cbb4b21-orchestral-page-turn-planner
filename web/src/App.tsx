import { FormEvent, useState } from 'react'

interface MeasureRow {
  height: string
  restAfterMs: string
}

interface TurnInfo {
  safe: boolean
  restAfterMs: number
  gapMs: number
}

interface PageDetail {
  index: number
  start: number
  end: number
  heightSum: number
  remaining: number
  turn: TurnInfo | null
}

interface PlanResponse {
  pageCapacity: number
  turnRequiredMs: number
  objective: {
    pages: number
    unsafeTurns: number
    maxGapMs: number
    slackSquares: number
  }
  breaks: number[]
  pages: PageDetail[]
}

interface ApiIssue {
  path: string
  message: string
}

const MAX_MEASURES = 500
const INT_LITERAL = /^(0|[1-9]\d*)$/
const FLOAT_LITERAL = /^-?\d+(\.\d+)?([eE][+-]?\d+)?$/

// Convert a raw input string into the JSON value to send. Valid integer
// literals become JSON numbers; anything else is forwarded as-is (decimal
// number or string) so the API remains the single source of validation and
// can reject it with a precise 422 error.
function toJsonValue(raw: string): unknown {
  const text = raw.trim()
  if (INT_LITERAL.test(text)) return Number.parseInt(text, 10)
  if (FLOAT_LITERAL.test(text)) return Number(text)
  return text
}

const SAMPLE_ROWS: MeasureRow[] = [
  { height: '42', restAfterMs: '0' },
  { height: '38', restAfterMs: '120' },
  { height: '55', restAfterMs: '0' },
  { height: '47', restAfterMs: '900' },
  { height: '60', restAfterMs: '0' },
  { height: '35', restAfterMs: '250' },
  { height: '52', restAfterMs: '0' },
  { height: '44', restAfterMs: '1400' },
  { height: '58', restAfterMs: '0' },
  { height: '40', restAfterMs: '80' },
  { height: '49', restAfterMs: '0' },
  { height: '36', restAfterMs: '600' },
]

export default function App() {
  const [pageCapacity, setPageCapacity] = useState('300')
  const [turnRequiredMs, setTurnRequiredMs] = useState('500')
  const [rows, setRows] = useState<MeasureRow[]>(SAMPLE_ROWS)
  const [plan, setPlan] = useState<PlanResponse | null>(null)
  const [issues, setIssues] = useState<ApiIssue[]>([])
  const [fatal, setFatal] = useState<string | null>(null)
  const [submitting, setSubmitting] = useState(false)

  function updateRow(index: number, field: keyof MeasureRow, value: string) {
    setRows((prev) => prev.map((row, i) => (i === index ? { ...row, [field]: value } : row)))
  }

  function addRows(count: number) {
    setRows((prev) => {
      const room = MAX_MEASURES - prev.length
      const extra = Array.from({ length: Math.min(count, room) }, () => ({
        height: '',
        restAfterMs: '',
      }))
      return [...prev, ...extra]
    })
  }

  function removeRow(index: number) {
    setRows((prev) => (prev.length <= 1 ? prev : prev.filter((_, i) => i !== index)))
  }

  function loadSample() {
    setPageCapacity('300')
    setTurnRequiredMs('500')
    setRows(SAMPLE_ROWS)
    setPlan(null)
    setIssues([])
    setFatal(null)
  }

  async function onSubmit(event: FormEvent) {
    event.preventDefault()
    setSubmitting(true)
    setFatal(null)
    const payload = {
      pageCapacity: toJsonValue(pageCapacity),
      turnRequiredMs: toJsonValue(turnRequiredMs),
      measures: rows.map((row) => ({
        height: toJsonValue(row.height),
        restAfterMs: toJsonValue(row.restAfterMs),
      })),
    }
    try {
      const response = await fetch('/api/plan', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      })
      if (response.ok) {
        setPlan((await response.json()) as PlanResponse)
        setIssues([])
      } else if (response.status === 422) {
        const body = (await response.json()) as { errors?: ApiIssue[] }
        setIssues(body.errors ?? [{ path: '$', message: '输入无效' }])
        setPlan(null) // 输入非法：清除旧方案
      } else {
        setFatal(`服务返回异常状态 ${response.status}`)
        setPlan(null)
      }
    } catch {
      setFatal('无法连接 API 服务，请确认服务已启动后重试')
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <main>
      <header className="hero">
        <h1>排练翻页规划</h1>
        <p>把 1–500 个小节分配到容量固定的页面上，让翻页永远落在足够长的休止里。</p>
      </header>

      <form onSubmit={onSubmit}>
        <fieldset className="globals">
          <label>
            pageCapacity · 每页容量（1–30000）
            <input
              value={pageCapacity}
              onChange={(e) => setPageCapacity(e.target.value)}
              inputMode="numeric"
              placeholder="例如 300"
            />
          </label>
          <label>
            turnRequiredMs · 翻页所需毫秒（0–30000）
            <input
              value={turnRequiredMs}
              onChange={(e) => setTurnRequiredMs(e.target.value)}
              inputMode="numeric"
              placeholder="例如 500"
            />
          </label>
        </fieldset>

        <table className="measures">
          <thead>
            <tr>
              <th>#</th>
              <th>height · 小节高度（1–30000，≤ 容量）</th>
              <th>restAfterMs · 小节后的休止（0–30000）</th>
              <th aria-label="操作" />
            </tr>
          </thead>
          <tbody>
            {rows.map((row, i) => (
              <tr key={i}>
                <td className="rownum">{i + 1}</td>
                <td>
                  <input
                    value={row.height}
                    onChange={(e) => updateRow(i, 'height', e.target.value)}
                    inputMode="numeric"
                    placeholder="高度"
                  />
                </td>
                <td>
                  <input
                    value={row.restAfterMs}
                    onChange={(e) => updateRow(i, 'restAfterMs', e.target.value)}
                    inputMode="numeric"
                    placeholder="休止毫秒"
                  />
                </td>
                <td>
                  <button
                    type="button"
                    className="link"
                    onClick={() => removeRow(i)}
                    disabled={rows.length <= 1}
                  >
                    删除
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>

        <div className="toolbar">
          <button type="button" onClick={() => addRows(1)}>
            ＋ 添加小节
          </button>
          <button type="button" onClick={() => addRows(10)}>
            ＋10 小节
          </button>
          <button type="button" onClick={loadSample}>
            载入示例
          </button>
          <span className="count">
            共 {rows.length} / {MAX_MEASURES} 小节
          </span>
        </div>

        <button type="submit" className="submit" disabled={submitting}>
          {submitting ? '计算中…' : '生成排页方案'}
        </button>
      </form>

      {fatal && <p className="fatal">{fatal}</p>}

      {issues.length > 0 && (
        <section className="errors">
          <h2>输入无效（{issues.length} 处），已清除旧方案</h2>
          <ul>
            {issues.map((issue, i) => (
              <li key={i}>
                <code>{issue.path}</code>：{issue.message}
              </li>
            ))}
          </ul>
        </section>
      )}

      {plan && (
        <section className="results">
          <h2>排页方案</h2>
          <p className="objective">
            目标向量：页数 <strong>{plan.objective.pages}</strong> · 不安全翻页{' '}
            <strong>{plan.objective.unsafeTurns}</strong> · 最大休止缺口{' '}
            <strong>{plan.objective.maxGapMs} ms</strong> · 剩余容量平方和{' '}
            <strong>{plan.objective.slackSquares}</strong>
          </p>
          <p className="breaks">
            分页点（非末页末小节的 1 基序号）：
            {plan.breaks.length > 0 ? plan.breaks.join('、') : '无（全部在一页）'}
          </p>
          <ol className="pages">
            {plan.pages.map((page) => (
              <li
                key={page.index}
                className={
                  page.turn === null ? 'page last' : page.turn.safe ? 'page safe' : 'page unsafe'
                }
              >
                <header>
                  第 {page.index} 页 · 小节 {page.start}–{page.end}
                </header>
                <p>
                  占用高度 {page.heightSum} / {plan.pageCapacity}（剩余 {page.remaining}）
                </p>
                {page.turn === null ? (
                  <p className="turn none">末页 · 无需翻页</p>
                ) : page.turn.safe ? (
                  <p className="turn ok">
                    ✓ 翻页安全：末小节休止 {page.turn.restAfterMs} ms ≥ 需要{' '}
                    {plan.turnRequiredMs} ms
                  </p>
                ) : (
                  <p className="turn bad">
                    ✗ 翻页危险：休止 {page.turn.restAfterMs} ms 不足 {plan.turnRequiredMs}{' '}
                    ms，缺口 {page.turn.gapMs} ms
                  </p>
                )}
              </li>
            ))}
          </ol>
        </section>
      )}
    </main>
  )
}
