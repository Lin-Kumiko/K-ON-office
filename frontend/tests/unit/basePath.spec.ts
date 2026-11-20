import { afterEach, describe, expect, it, vi } from 'vitest'
import { normalizeBase, withBase } from '@/utils/basePath'

afterEach(() => {
  vi.unstubAllEnvs()
})

describe('normalizeBase', () => {
  it('defaults to the site root', () => {
    expect(normalizeBase(undefined)).toBe('/')
    expect(normalizeBase(null)).toBe('/')
    expect(normalizeBase('')).toBe('/')
    expect(normalizeBase('   ')).toBe('/')
    expect(normalizeBase('/')).toBe('/')
  })

  it('adds the missing slashes and squeezes extra ones', () => {
    expect(normalizeBase('k-on')).toBe('/k-on/')
    expect(normalizeBase('/k-on')).toBe('/k-on/')
    expect(normalizeBase('/k-on/')).toBe('/k-on/')
    expect(normalizeBase('//k-on//')).toBe('/k-on/')
    expect(normalizeBase('works/k-on')).toBe('/works/k-on/')
  })
})

describe('withBase', () => {
  it('leaves URLs unchanged at the site root', () => {
    expect(withBase('/api/x', '/')).toBe('/api/x')
  })

  it('prefixes root-relative URLs, keeping the query string', () => {
    expect(withBase('/api/x?y=1', '/k-on/')).toBe('/k-on/api/x?y=1')
    expect(withBase('/', '/k-on/')).toBe('/k-on/')
  })

  it('does not touch absolute, protocol-relative or relative URLs', () => {
    expect(withBase('https://example.com/a', '/k-on/')).toBe('https://example.com/a')
    expect(withBase('//cdn.example.com/a', '/k-on/')).toBe('//cdn.example.com/a')
    expect(withBase('api/x', '/k-on/')).toBe('api/x')
  })

  it('accepts a base given without slashes', () => {
    expect(withBase('/api/x', 'k-on')).toBe('/k-on/api/x')
  })

  it('reads the build-time base when none is passed', () => {
    vi.stubEnv('BASE_URL', '/k-on/')
    expect(withBase('/api/x')).toBe('/k-on/api/x')
  })
})
