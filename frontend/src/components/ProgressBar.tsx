export default function ProgressBar({ progress }: { progress: any }) {
  const total = progress?.total || 0
  const sold = progress?.sold || 0
  const pct = total ? Math.round((sold / total) * 100) : 0

  return (
    <section id="raffleProgress" className="raffle-progress">
      <div className="progress-track">
        <div className="progress-fill" style={{ width: `${pct}%` }} />
      </div>
      <div className="progress-meta">
        <span id="soldCount">{sold}</span> vendidos de <span id="totalCount">{total}</span> — <strong>{pct}%</strong>
      </div>
    </section>
  )
}
