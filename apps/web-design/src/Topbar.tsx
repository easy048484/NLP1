export function Topbar({
  title,
  subtitle,
  onBack,
}: {
  title: string;
  subtitle?: string;
  onBack?: () => void;
}) {
  return (
    <header className="topbar">
      {onBack && (
        <button type="button" className="back-btn" onClick={onBack} aria-label="뒤로">
          ←
        </button>
      )}
      <div>
        <h2>{title}</h2>
        {subtitle && <p>{subtitle}</p>}
      </div>
    </header>
  );
}
