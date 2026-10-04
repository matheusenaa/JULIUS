import { Link } from "react-router";

/** Símbolo JULIUS: um "J" desenhado como símbolo de moeda (traço duplo, como ¥ e €). */
export function Mark({ size = 30, round = false }: { size?: number; round?: boolean }) {
  return (
    <svg width={size} height={size} viewBox="0 0 64 64" aria-hidden="true" className={round ? "avatar" : undefined}>
      <rect width="64" height="64" rx={round ? 32 : 15} fill="#0B3D2C" />
      <path d="M36 13v25.5a10.5 10.5 0 0 1-21 0" fill="none" stroke="#fff" strokeWidth="7" strokeLinecap="round" />
      <path d="M27.5 22.5h17M27.5 30h17" stroke="#F0507E" strokeWidth="3.6" strokeLinecap="round" />
    </svg>
  );
}

export function Logo({ to = "/" }: { to?: string }) {
  return (
    <Link to={to} className="logo" aria-label="JULIUS — início">
      <Mark />
      <span className="wordmark">JULIUS</span>
    </Link>
  );
}

export const TAGLINE = "Cada centavo tem destino.";

export function Splash() {
  return (
    <div className="splash" role="status" aria-label="Carregando o JULIUS">
      <Mark size={72} />
      <div className="wordmark">JULIUS</div>
      <div className="tagline">{TAGLINE}</div>
    </div>
  );
}

export function AssistantAvatar() {
  return <Mark size={30} round />;
}
