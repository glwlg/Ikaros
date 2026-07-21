import assert from 'node:assert/strict'
import test from 'node:test'

import {
    accountingErrorMessage,
    accountingToast,
    dismissAccountingToast,
    subscribeAccountingToast,
} from '../src/utils/accountingToast.ts'

test('accountingErrorMessage extracts axios detail and network errors', () => {
    assert.equal(
        accountingErrorMessage({ response: { data: { detail: '权限不足' } } }),
        '权限不足',
    )
    assert.equal(
        accountingErrorMessage({ message: 'Network Error' }),
        '网络异常，请检查连接后重试',
    )
    assert.equal(accountingErrorMessage(null, '默认失败'), '默认失败')
})

test('toast queue notifies subscribers and dismisses', () => {
    const seen: number[] = []
    const unsub = subscribeAccountingToast(items => {
        seen.push(items.length)
    })

    const id = accountingToast('hello', { type: 'success', duration: 0 })
    assert.ok(id > 0)
    assert.ok(seen[seen.length - 1]! >= 1)

    dismissAccountingToast(id)
    assert.equal(seen[seen.length - 1], 0)
    unsub()
})
