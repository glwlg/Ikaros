import assert from 'node:assert/strict'
import test from 'node:test'

import {
    buildRecordListQuery,
    monthWindow,
    periodBounds,
    toDateOnly,
    toIsoLocalDateTime,
} from '../src/utils/accountingNavigation.ts'

test('buildRecordListQuery omits empty and special “all” values', () => {
    const q = buildRecordListQuery({
        type: '支出',
        category: '餐饮',
        account: '现金',
        start: new Date(2026, 2, 1, 0, 0, 0),
        end: new Date(2026, 3, 1, 0, 0, 0),
        label: '近1月',
    })
    assert.equal(q.type, '支出')
    assert.equal(q.category, '餐饮')
    assert.equal(q.account, '现金')
    assert.equal(q.label, '近1月')
    assert.equal(q.start, toIsoLocalDateTime(new Date(2026, 2, 1, 0, 0, 0)))
    assert.equal(q.end, toIsoLocalDateTime(new Date(2026, 3, 1, 0, 0, 0)))

    const empty = buildRecordListQuery({
        type: '全部',
        category: '全部分类',
        account: '',
    })
    assert.deepEqual(empty, {})
})

test('buildRecordListQuery drops 结余 type filter', () => {
    const q = buildRecordListQuery({ type: '结余', category: '未分类' })
    assert.equal(q.type, undefined)
    assert.equal(q.category, '未分类')
})

test('buildRecordListQuery keeps 未分类 as a real category filter', () => {
    const q = buildRecordListQuery({ category: '未分类', type: '支出' })
    assert.equal(q.category, '未分类')
    assert.equal(q.type, '支出')
    // Must not treat 未分类 like “all categories”
    assert.notEqual(q.category, undefined)
    assert.notEqual(q.category, '')
})

test('periodBounds resolves day/month/quarter/year', () => {
    const day = periodBounds('2026-03-14', 'day')
    assert.ok(day)
    assert.equal(toDateOnly(day.start), '2026-03-14')
    assert.equal(toDateOnly(day.end), '2026-03-15')

    const month = periodBounds('2026-03', 'month')
    assert.ok(month)
    assert.equal(toDateOnly(month.start), '2026-03-01')
    assert.equal(toDateOnly(month.end), '2026-04-01')

    const quarter = periodBounds('2026-Q2', 'quarter')
    assert.ok(quarter)
    assert.equal(toDateOnly(quarter.start), '2026-04-01')
    assert.equal(toDateOnly(quarter.end), '2026-07-01')

    const year = periodBounds('2026', 'year')
    assert.ok(year)
    assert.equal(toDateOnly(year.start), '2026-01-01')
    assert.equal(toDateOnly(year.end), '2027-01-01')
})

test('monthWindow matches budget calendar month', () => {
    const w = monthWindow(2026, 3)
    assert.equal(toDateOnly(w.start), '2026-03-01')
    assert.equal(toDateOnly(w.end), '2026-04-01')
    assert.match(w.label, /3月/)
})
