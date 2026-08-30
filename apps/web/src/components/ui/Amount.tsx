import type { TaxResult } from "../../types";
import { formatWon, formatWonExact, formatDateKo } from "../../lib/format";

/** 큰 금액 강조 (세리프). 네이비 카드 위/아래 모두 사용 가능. */
export function AmountDisplay({
  label,
  amount,
  note,
  tone = "default",
}: {
  label: string;
  amount: number | null | undefined;
  note?: string;
  tone?: "default" | "inverse";
}) {
  return (
    <div className={`amount-display amount-${tone}`}>
      <div className="amount-label">{label}</div>
      <div className="amount-value">{formatWon(amount)}</div>
      {note && <p className="amount-note">{note}</p>}
    </div>
  );
}

/**
 * 상속세 8항목 내역. tax_calculator 의 data["last_result"].
 * 마지막 행(최종 예상 상속세)은 강조.
 */
export function TaxBreakdown({ result }: { result: TaxResult }) {
  return (
    <div className="tax-breakdown">
      <table>
        <tbody>
          {result.rows.map((row, i) => (
            <tr key={row.label} className={i === result.rows.length - 1 ? "tax-row-final" : ""}>
              <th scope="row">{row.label}</th>
              <td>{formatWonExact(row.amount)}</td>
            </tr>
          ))}
        </tbody>
      </table>
      {result.filing_due && (
        <p className="tax-filing-due">
          예상 신고기한 <strong>{formatDateKo(result.filing_due)}</strong>
        </p>
      )}
      {result.notes && result.notes.length > 0 && (
        <ul className="tax-notes">
          {result.notes.map((n) => (
            <li key={n}>{n}</li>
          ))}
        </ul>
      )}
    </div>
  );
}
