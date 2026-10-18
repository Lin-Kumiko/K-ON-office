import { describe, expect, it } from 'vitest'
import { fmtDateTime, fmtTime, hoursToDays, money, statusText, statusType, sumMoney } from '@/utils/format'

describe('format helpers', () => {
  it('sums money exactly in cents (no float drift)', () => {
    expect(sumMoney(['0.10', '0.20'])).toBe('0.30')
    expect(sumMoney(['1200.10', '88.80'])).toBe('1288.90')
    expect(sumMoney(['1', '2.5', 'abc', '', '3.333'])).toBe('3.50') // invalid entries ignored
  })

  it('formats money, durations and times', () => {
    expect(money('1288.9')).toBe('¥1,288.90')
    expect(money(null)).toBe('-')
    expect(hoursToDays(32)).toBe('4 天')
    expect(hoursToDays(4)).toBe('0.5 天')
    expect(fmtDateTime('2026-10-19T09:05:00')).toBe('2026-10-19 09:05')
    expect(fmtTime(null)).toBe('--:--')
  })

  it('maps statuses to labels and tag types', () => {
    expect(statusText('pending')).toBe('审批中')
    expect(statusText('late_early')).toBe('迟到+早退')
    expect(statusText('unknown_state')).toBe('unknown_state')
    expect(statusType('rejected')).toBe('danger')
    expect(statusType(undefined)).toBe('info')
  })
})
