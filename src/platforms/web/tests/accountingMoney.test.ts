import assert from 'node:assert/strict'
import test from 'node:test'

import {
    budgetProgressPercent,
    debtRemainingLabel,
    formatCompactMoneyAmount,
    formatDayGroupLabel,
    formatMoneyAmount,
    groupRecordsByDay,
    nextRecordsLimit,
    normalizeMoneySettings,
    recordDateKey,
    recordsPageHasMore,
    ringDashOffset,
    summarizeDebtRemaining,
} from '../src/utils/accountingMoney.ts'

test('formatMoneyAmount honors currency symbols and decimal places', () => {
    assert.equal(
        formatMoneyAmount(1234.5, { currency_symbol: '¥', decimal_places: 2 }),
        '¥1,234.50',
    )
    assert.equal(
        formatMoneyAmount(1234.5, { currency_symbol: '$', decimal_places: 0 }),
        '$1,235',
    )
    assert.equal(
        formatMoneyAmount(10, { currency_symbol: '€', decimal_places: 2 }, { signed: true }),
        '+€10.00',
    )
    assert.equal(
        formatMoneyAmount(-20.1, { currency_symbol: '¥', decimal_places: 1 }),
        '-¥20.1',
    )
})

test('formatCompactMoneyAmount uses 万/亿 for large amounts', () => {
    const s = { currency_symbol: '¥', decimal_places: 2 }
    assert.equal(formatCompactMoneyAmount(1966688, s), '¥196.67万')
    assert.equal(formatCompactMoneyAmount(9999.5, s), '¥9,999.50')
    assert.equal(formatCompactMoneyAmount(10_000, s), '¥1万')
    assert.equal(formatCompactMoneyAmount(123_456_789, s), '¥1.23亿')
    assert.equal(formatCompactMoneyAmount(-25_000, s), '-¥2.5万')
})

test('normalizeMoneySettings clamps decimal places', () => {
    assert.equal(normalizeMoneySettings({ decimal_places: 9 }).decimal_places, 4)
    assert.equal(normalizeMoneySettings({ decimal_places: -2 }).decimal_places, 0)
    assert.equal(normalizeMoneySettings(null).currency_symbol, '¥')
})

test('summarizeDebtRemaining aggregates unsettled rows by type', () => {
    const summary = summarizeDebtRemaining([
        { type: '借入', remaining_amount: 100, is_settled: false },
        { type: '借入', remaining_amount: 50, is_settled: true },
        { type: '借出', remaining_amount: 80 },
        { type: '报销', remaining_amount: 20 },
        { type: '报销', remaining_amount: 0 },
        { type: '其他', remaining_amount: 999 },
    ])
    assert.equal(summary.borrow, 100)
    assert.equal(summary.lend, 80)
    assert.equal(summary.reimburse, 20)

    assert.equal(
        debtRemainingLabel('借入', summary, { currency_symbol: '¥', decimal_places: 0 }),
        '¥100 待还',
    )
    assert.equal(
        debtRemainingLabel('借出', summary, { currency_symbol: '$', decimal_places: 0 }),
        '$80 待收',
    )
    assert.equal(
        debtRemainingLabel('报销', summary, { currency_symbol: '¥', decimal_places: 0 }),
        '¥20 待报',
    )
})

test('groupRecordsByDay builds date keys and labels', () => {
    const now = new Date(2026, 2, 14, 12, 0, 0)
    const groups = groupRecordsByDay(
        [
            { id: 1, record_time: '2026-03-14T10:00:00' },
            { id: 2, record_time: '2026-03-13T09:00:00' },
            { id: 3, record_time: '2026-03-14T18:00:00' },
            { id: 4, record_time: '2026-03-10T08:00:00' },
        ],
        now,
    )

    assert.equal(groups.length, 3)
    assert.equal(groups[0]?.dateKey, '2026-03-14')
    assert.equal(groups[0]?.label, '今天')
    assert.equal(groups[0]?.records.map(r => r.id).join(','), '1,3')
    assert.equal(groups[1]?.label, '昨天')
    assert.equal(groups[2]?.label, '3月10日')
    assert.equal(recordDateKey('2026-03-14T19:25:42'), '2026-03-14')
    assert.equal(formatDayGroupLabel('2026-03-14', now), '今天')
})

test('nextRecordsLimit and hasMore support load-more pagination', () => {
    assert.equal(recordsPageHasMore(50, 50), true)
    assert.equal(recordsPageHasMore(12, 50), false)
    assert.equal(nextRecordsLimit(50, 50, true), 100)
    assert.equal(nextRecordsLimit(50, 50, false), null)
})

test('budget ring helpers clamp progress', () => {
    assert.equal(budgetProgressPercent(50, 100), 50)
    assert.equal(budgetProgressPercent(150, 100), 100)
    assert.equal(budgetProgressPercent(10, 0), 0)
    const c = 2 * Math.PI * 40
    assert.equal(ringDashOffset(0, c), c)
    assert.equal(ringDashOffset(100, c), 0)
    assert.ok(Math.abs(ringDashOffset(50, c) - c / 2) < 1e-9)
})
