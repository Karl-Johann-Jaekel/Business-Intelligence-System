import { describe, expect, it } from 'vitest'
import { buildUrl } from './api'
import { niceTicks } from './charts/scale'
import { assignSlots } from './components/colors'
import { parseUrlState, presetWindow, serializeUrlState, windowForGrain } from './dates'
import { changeIcon, changeTone, formatChange, formatPct, formatValue } from './format'

describe('changeTone uses registry direction', () => {
  it('rates increases by direction', () => {
    expect(changeTone(5, 'higher_is_better')).toBe('good')
    expect(changeTone(5, 'lower_is_better')).toBe('bad')
    expect(changeTone(-5, 'lower_is_better')).toBe('good')
    expect(changeTone(5, 'neutral')).toBe('neutral')
    expect(changeTone(null, 'higher_is_better')).toBe('neutral')
    // arrow follows the sign, independent of whether the change is good
    expect(changeIcon(-54)).toBe('▼')
    expect(changeIcon(3)).toBe('▲')
  })
})

// Intl uses non-breaking spaces before units; compare with plain spaces.
const plain = (s: string) => s.replace(/\u00a0/g, ' ')

describe('formatValue by unit', () => {
  it('formats every registry unit', () => {
    expect(plain(formatValue(0.0214, 'ratio'))).toBe('2,14 %')
    expect(plain(formatValue(0.164, 'ratio'))).toBe('16,4 %')
    expect(plain(formatValue(12.89, 'days'))).toBe('12,9 Tage')
    expect(plain(formatValue(4.025, 'score'))).toBe('4,03')
    expect(plain(formatValue(1284, 'count'))).toBe('1.284')
    expect(plain(formatValue(1.1428, 'count'))).toBe('1,14')
    expect(plain(formatValue(null, 'BRL'))).toBe('–')
  })
  it('signs percentage changes', () => {
    expect(formatPct(12.34)).toBe('+12,3 %')
    expect(formatPct(-5)).toBe('−5 %')
    expect(formatPct(null)).toBe('–')
    expect(formatPct(-0.004, 'pp', 2)).toBe('±0 pp')
  })
  it('reports ratio changes in percentage points, others in percent', () => {
    expect(formatChange({ change_abs: -0.003, change_pct: -12 }, 'ratio')).toBe('−0,3 pp')
    expect(formatChange({ change_abs: 0.00034, change_pct: 2.3 }, 'ratio')).toBe('+0,03 pp')
    expect(formatChange({ change_abs: 5, change_pct: 12 }, 'BRL')).toBe('+12 %')
    expect(plain(formatValue(8.2196, 'multiple'))).toBe('8,22×')
  })
})

describe('assignSlots keeps colour with the entity', () => {
  it('survivors keep their slot and newcomers take the lowest free slot', () => {
    const first = assignSlots(['region:SP', 'region:RJ', 'region:MG'], new Map())
    expect([...first.values()]).toEqual([0, 1, 2])
    const second = assignSlots(['region:MG', 'region:PR'], first)
    expect(second.get('region:MG')).toBe(2)
    expect(second.get('region:PR')).toBe(0)
  })
  it('refuses more series than validated slots', () => {
    expect(() => assignSlots(['a', 'b', 'c', 'd', 'e', 'f'], new Map())).toThrow()
  })
})

describe('niceTicks', () => {
  it('covers the range with clean steps', () => {
    expect(niceTicks(0, 950)).toEqual([0, 250, 500, 750, 1000])
    expect(niceTicks(0, 0.034)).toEqual([0, 0.01, 0.02, 0.03, 0.04])
  })
})

describe('windows', () => {
  it('builds preset and monthly windows', () => {
    expect(presetWindow('2018-03-31', 90)).toEqual({ start: '2018-01-01', end: '2018-03-31' })
    expect(windowForGrain({ start: '2018-01-15', end: '2018-03-31' }, 'month')).toEqual({
      start: '2018-01-01',
      end: '2018-03-01',
    })
  })
  it('builds query strings with repeated values and drops empty ones', () => {
    expect(buildUrl('/kpis/gmv/series', { dim: 'region', value: ['SP', 'RJ'], to: undefined })).toBe(
      '/api/v1/kpis/gmv/series?dim=region&value=SP&value=RJ',
    )
  })
})

describe('url state', () => {
  it('round-trips filters and rejects malformed values', () => {
    const state = parseUrlState('?kpi=gmv&dim=region&range=30d')
    expect(state).toEqual({ presetId: '30d', custom: null, kpi: 'gmv', dim: 'region' })
    expect(serializeUrlState(state)).toBe('?kpi=gmv&dim=region&range=30d')
    expect(parseUrlState('?from=2018-02-01&to=2018-01-01&range=bogus').presetId).toBe('90d')
    expect(parseUrlState('?from=2018-01-01&to=2018-02-01').custom).toEqual({ start: '2018-01-01', end: '2018-02-01' })
  })
})
