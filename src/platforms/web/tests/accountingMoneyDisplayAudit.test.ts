import assert from 'node:assert/strict'
import fs from 'node:fs'
import path from 'node:path'
import test from 'node:test'
import { fileURLToPath } from 'node:url'

/**
 * Static audit: templates/scripts must not prefix formatAccountingMoney with a
 * literal currency symbol (¥ / $ / €). The shipped formatter already includes
 * currency_symbol from global settings.
 */
const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..')
const scanDirs = [
    path.join(root, 'src/views/Accounting'),
    path.join(root, 'src/components/accounting'),
]

const forbidden = [
    /¥\{\{\s*formatAccountingMoney\s*\(/,
    /\$\{\{\s*formatAccountingMoney\s*\(/,
    /€\{\{\s*formatAccountingMoney\s*\(/,
    /`¥\$\{\s*formatAccountingMoney\s*\(/,
    /`\$\$\{\s*formatAccountingMoney\s*\(/,
    /`€\$\{\s*formatAccountingMoney\s*\(/,
    /-¥\$\{\s*formatAccountingMoney\s*\(/,
    /\+¥\{\{\s*formatAccountingMoney\s*\(/,
    /-¥\{\{\s*formatAccountingMoney\s*\(/,
    /'¥0'/,
    /"¥0"/,
    /`¥0`/,
    />¥0</,
]

function walk(dir: string): string[] {
    if (!fs.existsSync(dir)) return []
    const out: string[] = []
    for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
        const full = path.join(dir, entry.name)
        if (entry.isDirectory()) out.push(...walk(full))
        else if (/\.(vue|ts|tsx|js)$/.test(entry.name)) out.push(full)
    }
    return out
}

test('accounting views do not double-prefix formatAccountingMoney with currency symbols', () => {
    const files = scanDirs.flatMap(walk)
    assert.ok(files.length > 0, 'expected accounting source files to exist')

    const violations: string[] = []
    for (const file of files) {
        const text = fs.readFileSync(file, 'utf8')
        for (const pattern of forbidden) {
            if (pattern.test(text)) {
                const rel = path.relative(root, file)
                // find line numbers for message
                text.split('\n').forEach((line, idx) => {
                    if (pattern.test(line)) {
                        violations.push(`${rel}:${idx + 1}: ${line.trim()}`)
                    }
                })
            }
        }
    }

    assert.deepEqual(violations, [], `currency double-prefix violations:\n${violations.join('\n')}`)
})

test('formatAccountingMoney-like shipped helper embeds the symbol once', async () => {
    const { formatMoneyAmount } = await import('../src/utils/accountingMoney.ts')
    assert.equal(formatMoneyAmount(12, { currency_symbol: '¥', decimal_places: 2 }), '¥12.00')
    assert.equal(formatMoneyAmount(12, { currency_symbol: '$', decimal_places: 0 }), '$12')
    // Must not be callable as "already includes symbol" and still need a prefix
    assert.notEqual(`¥${formatMoneyAmount(12, { currency_symbol: '¥', decimal_places: 0 })}`, '¥12')
    assert.match(`¥${formatMoneyAmount(12, { currency_symbol: '¥', decimal_places: 0 })}`, /^¥¥/)
})
