export default function RaffleHeader({ config }: { config: any }) {
  return (
    <header id="raffleHeader" className="raffle-header">
      <div className="raffle-header__left">
        <img id="raffleCoverImg" src={config?.image_url || '/placeholder.png'} alt={config?.name} />
      </div>
      <div className="raffle-header__right">
        <h1 id="raffleTitle">{config?.name}</h1>
        <p id="raffleDesc">{config?.description}</p>
        {/* Aquí puedes poner info de precio, métodos de pago, etc. */}
      </div>
    </header>
  )
}
