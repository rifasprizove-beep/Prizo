import { useState } from 'react'
import { postQuote, reserveTickets, submitReservedPayment, uploadEvidence } from '../services/api'

export default function BuySection({ raffleId }: { raffleId: string; config: any }) {
  const [email, setEmail] = useState('')
  const [qty, setQty] = useState(1)
  const [quote, setQuote] = useState<any>(null)
  const [ticketIds, setTicketIds] = useState<string[] | null>(null)
  const [evidenceUrl, setEvidenceUrl] = useState<string | null>(null)
  const [uploading, setUploading] = useState(false)

  async function handleReserve() {
    const r = await reserveTickets({ raffle_id: raffleId, email, quantity: qty })
    setTicketIds(r.ticket_ids || r.tickets || null)
  }

  async function handleQuote() {
    const q = await postQuote({ raffle_id: raffleId, quantity: qty, method: 'pago_movil' })
    setQuote(q)
  }

  async function handleUpload(file: File) {
    setUploading(true)
    try {
      const res = await uploadEvidence(file)
      setEvidenceUrl(res.secure_url || res.url)
    } finally {
      setUploading(false)
    }
  }

  async function handleSubmit() {
    if (!ticketIds || !evidenceUrl) return
    await submitReservedPayment({
      raffle_id: raffleId,
      email,
      ticket_ids: ticketIds,
      evidence_url: evidenceUrl,
      method: 'pago_movil',
    })
    alert('Pago enviado. Te notificaremos por correo.')
  }

  return (
    <section id="buySection" className="buy-section">
      <h2>Comprar tickets</h2>

      <div className="buy-form">
        <label>
          Correo
          <input id="buyerEmail" type="email" value={email} onChange={(e) => setEmail(e.target.value)} />
        </label>

        <label>
          Cantidad
          <input id="ticketQty" type="number" min={1} value={qty} onChange={(e) => setQty(+e.target.value)} />
        </label>

        <div className="buy-actions">
          <button id="reserveBtn" onClick={handleReserve}>Reservar</button>
          <button id="quoteBtn" onClick={handleQuote}>Cotizar</button>
        </div>

        {quote && (
          <div id="quoteBox" className="quote-box">
            <p>Total en Bs: <strong>{quote.total_ves}</strong></p>
          </div>
        )}

        <div className="evidence-upload">
          <label className="file">
            Cargar comprobante
            <input
              id="evidenceInput"
              type="file"
              accept="image/*,application/pdf"
              onChange={(e) => e.target.files && handleUpload(e.target.files[0])}
            />
          </label>
          {uploading && <span>Subiendo…</span>}
          {evidenceUrl && <a id="evidenceUrl" href={evidenceUrl} target="_blank">Ver comprobante</a>}
        </div>

        <button id="submitPaymentBtn" disabled={!ticketIds || !evidenceUrl} onClick={handleSubmit}>
          Enviar pago
        </button>
      </div>
    </section>
  )
}
