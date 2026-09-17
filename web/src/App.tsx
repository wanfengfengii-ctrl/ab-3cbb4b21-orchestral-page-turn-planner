import { useState, type FormEvent, type ReactNode } from "react";
import { solve, ValidationFailedError } from "./api";
import type { ApiError, PageInfo, SolveResponse } from "./types";

interface MeasureRow {
  height: string;
  restAfterMs: string;
}

const MAX_MEASURES = 500;

const SAMPLE_MEASURES: MeasureRow[] = [
  { height: "420", restAfterMs: "1200" },
  { height: "380", restAfterMs: "0" },
  { height: "460", restAfterMs: "300" },
  { height: "300", restAfterMs: "900" },
  { height: "520", restAfterMs: "0" },
  { height: "260", restAfterMs: "1500" },
  { height: "410", restAfterMs: "200" },
  { height: "350", restAfterMs: "0" },
];

/**
 * Convert a raw input string into the JSON value sent to the API.  Only
 * tokens that already match the required integer lexical form become JSON
 * numbers; everything else is forwarded verbatim (string or null) so the
 * API can reject it with a precise, per-field 422 error.
 */
function toJsonValue(raw: string): unknown {
  const text = raw.trim();
  if (text === "") return null;
  if (/^-?(0|[1-9]\d*)$/.test(text)) {
    const value = Number(text);
    return Number.isSafeInteger(value) ? value : text;
  }
  return text;
}

export default function App() {
  const [pageCapacity, setPageCapacity] = useState("1500");
  const [turnRequiredMs, setTurnRequiredMs] = useState("800");
  const [measures, setMeasures] = useState<MeasureRow[]>(SAMPLE_MEASURES);
  const [plan, setPlan] = useState<SolveResponse | null>(null);
  const [fieldErrors, setFieldErrors] = useState<ApiError[] | null>(null);
  const [fatalError, setFatalError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  const updateMeasure = (index: number, key: keyof MeasureRow, value: string) => {
    setMeasures((prev) =>
      prev.map((row, i) => (i === index ? { ...row, [key]: value } : row)),
    );
  };

  const addMeasure = () => {
    setMeasures((prev) =>
      prev.length >= MAX_MEASURES
        ? prev
        : [...prev, { height: "", restAfterMs: "" }],
    );
  };

  const removeMeasure = (index: number) => {
    setMeasures((prev) =>
      prev.length <= 1 ? prev : prev.filter((_, i) => i !== index),
    );
  };

  async function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setSubmitting(true);
    const payload = {
      pageCapacity: toJsonValue(pageCapacity),
      turnRequiredMs: toJsonValue(turnRequiredMs),
      measures: measures.map((row) => ({
        height: toJsonValue(row.height),
        restAfterMs: toJsonValue(row.restAfterMs),
      })),
    };
    try {
      const next = await solve(payload);
      setPlan(next);
      setFieldErrors(null);
      setFatalError(null);
    } catch (error) {
      // 输入非法（或请求失败）时清除旧方案，只展示本次结果。
      setPlan(null);
      if (error instanceof ValidationFailedError) {
        setFieldErrors(error.errors);
        setFatalError(null);
      } else {
        setFieldErrors(null);
        setFatalError(error instanceof Error ? error.message : String(error));
      }
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div className="layout">
      <header className="header">
        <h1>管弦乐翻页编排</h1>
        <p>
          将 1–500 个小节划分为连续页，依次最小化：页数 → 不安全翻页数 →
          最大休止缺口 → 各页剩余容量平方和 → 翻页点字典序。
        </p>
      </header>

      <main className="main">
        <form className="column" onSubmit={onSubmit}>
          <section className="card">
            <h2>全局参数</h2>
            <div className="field-grid">
              <label className="field">
                <span>
                  页面容量 <code>pageCapacity</code>（1–30000）
                </span>
                <input
                  value={pageCapacity}
                  onChange={(e) => setPageCapacity(e.target.value)}
                  inputMode="numeric"
                  placeholder="例如 1500"
                />
              </label>
              <label className="field">
                <span>
                  翻页所需时长 <code>turnRequiredMs</code>（0–30000）
                </span>
                <input
                  value={turnRequiredMs}
                  onChange={(e) => setTurnRequiredMs(e.target.value)}
                  inputMode="numeric"
                  placeholder="例如 800"
                />
              </label>
            </div>
          </section>

          <section className="card">
            <div className="card-head">
              <h2>
                小节{" "}
                <span className="muted">
                  （{measures.length} / {MAX_MEASURES}）
                </span>
              </h2>
              <button
                type="button"
                className="ghost"
                onClick={addMeasure}
                disabled={measures.length >= MAX_MEASURES}
              >
                + 添加小节
              </button>
            </div>
            <div className="table-wrap">
              <table>
                <thead>
                  <tr>
                    <th>#</th>
                    <th>
                      高度 <code>height</code>（1–30000）
                    </th>
                    <th>
                      休止 <code>restAfterMs</code>（0–30000）
                    </th>
                    <th aria-label="操作" />
                  </tr>
                </thead>
                <tbody>
                  {measures.map((row, i) => (
                    <tr key={i}>
                      <td className="muted">{i + 1}</td>
                      <td>
                        <input
                          value={row.height}
                          onChange={(e) => updateMeasure(i, "height", e.target.value)}
                          inputMode="numeric"
                          placeholder="如 400"
                        />
                      </td>
                      <td>
                        <input
                          value={row.restAfterMs}
                          onChange={(e) =>
                            updateMeasure(i, "restAfterMs", e.target.value)
                          }
                          inputMode="numeric"
                          placeholder="如 800"
                        />
                      </td>
                      <td>
                        <button
                          type="button"
                          className="ghost danger"
                          onClick={() => removeMeasure(i)}
                          disabled={measures.length <= 1}
                        >
                          删除
                        </button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </section>

          <button className="primary" type="submit" disabled={submitting}>
            {submitting ? "计算中…" : "生成翻页方案"}
          </button>
        </form>

        <div className="column">
          {fieldErrors && (
            <section className="card error-card">
              <h2>输入校验失败（{fieldErrors.length} 处）</h2>
              <ul className="error-list">
                {fieldErrors.map((error, i) => (
                  <li key={i}>
                    <code>{error.path}</code>
                    <span>{error.message}</span>
                  </li>
                ))}
              </ul>
            </section>
          )}

          {fatalError && (
            <section className="card error-card">
              <h2>请求失败</h2>
              <p>{fatalError}</p>
            </section>
          )}

          {!plan && !fieldErrors && !fatalError && (
            <section className="card placeholder">
              <p>填写左侧表单并提交后，这里会展示最优翻页方案。</p>
            </section>
          )}

          {plan && (
            <>
              <section className="card">
                <h2>目标向量</h2>
                <div className="stat-grid">
                  <Stat label="页数" value={plan.objective.pages} />
                  <Stat label="不安全翻页" value={plan.objective.unsafeTurns} />
                  <Stat
                    label="最大休止缺口"
                    value={`${plan.objective.maxGapMs.toLocaleString()} ms`}
                  />
                  <Stat
                    label="剩余容量平方和"
                    value={plan.objective.sumSquaredSlack.toLocaleString()}
                  />
                </div>
                <p className="turn-points">
                  翻页点（非末页末小节序号）：
                  {plan.turnPoints.length > 0
                    ? plan.turnPoints.join("、")
                    : "无（全部内容仅一页）"}
                </p>
              </section>

              <section className="card">
                <h2>分页明细</h2>
                <div className="page-list">
                  {plan.pages.map((page) => (
                    <PageCard key={page.page} page={page} />
                  ))}
                </div>
              </section>
            </>
          )}
        </div>
      </main>
    </div>
  );
}

function Stat({ label, value }: { label: string; value: ReactNode }) {
  return (
    <div className="stat">
      <div className="stat-value">{value}</div>
      <div className="stat-label">{label}</div>
    </div>
  );
}

function PageCard({ page }: { page: PageInfo }) {
  const capacity = page.usedHeight + page.remainingCapacity;
  const percent = capacity > 0 ? (page.usedHeight / capacity) * 100 : 0;

  return (
    <article className="page-card">
      <div className="page-head">
        <strong>第 {page.page} 页</strong>
        <span className="muted">
          小节 {page.startMeasure}–{page.endMeasure}（{page.measureCount} 个）
        </span>
        {page.isLastPage ? (
          <span className="badge last">末页 · 无需翻页</span>
        ) : page.turn?.safe ? (
          <span className="badge safe">翻页安全</span>
        ) : (
          <span className="badge unsafe">
            翻页不安全 · 缺口 {page.turn?.gapMs.toLocaleString()} ms
          </span>
        )}
      </div>
      <div
        className="bar"
        role="img"
        aria-label={`占用高度 ${page.usedHeight}，容量 ${capacity}`}
      >
        <div className="bar-fill" style={{ width: `${percent}%` }} />
      </div>
      <div className="page-meta">
        占用高度 {page.usedHeight.toLocaleString()} / 剩余{" "}
        {page.remainingCapacity.toLocaleString()}
        {page.turn && (
          <>
            {" "}
            · 休止 {page.turn.restAfterMs.toLocaleString()} ms / 需要{" "}
            {page.turn.requiredMs.toLocaleString()} ms
          </>
        )}
      </div>
    </article>
  );
}
