/**
 * View-facing money formatter that reads saved global accounting settings.
 */
import { loadGlobalSettings } from './accountingLocal'
import {
    formatCompactMoneyAmount,
    formatMoneyAmount,
    type MoneyFormatSettings,
} from './accountingMoney'

export function getAccountingMoneySettings(): MoneyFormatSettings {
    const s = loadGlobalSettings()
    return {
        currency_symbol: s.currency_symbol,
        decimal_places: s.decimal_places,
    }
}

export function formatAccountingMoney(
    amount: number,
    options?: { signed?: boolean; abs?: boolean; settings?: Partial<MoneyFormatSettings> | null },
): string {
    const settings = options?.settings ?? getAccountingMoneySettings()
    return formatMoneyAmount(amount, settings, {
        signed: options?.signed,
        abs: options?.abs,
    })
}

/** Compact money for tight UI (profile hero stats etc.): 万 / 亿. */
export function formatCompactAccountingMoney(
    amount: number,
    options?: { settings?: Partial<MoneyFormatSettings> | null },
): string {
    const settings = options?.settings ?? getAccountingMoneySettings()
    return formatCompactMoneyAmount(amount, settings)
}
