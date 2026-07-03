export const siteUrl = 'https://plainquery.in'

export const siteName = 'PlainQuery'

export const siteTitle = 'PlainQuery — ask your database in plain English'

export const siteDescription =
  'PlainQuery is an open-source MCP server and hosted app that lets ChatGPT, Cursor, VS Code, and Claude Desktop query Postgres in plain English with read-only SQL validation.'

export const seoKeywords = [
  'PlainQuery',
  'MCP server',
  'Model Context Protocol',
  'Postgres MCP server',
  'PostgreSQL AI query',
  'text to SQL',
  'natural language database query',
  'ask database in plain English',
  'Cursor MCP',
  'Claude Desktop MCP',
  'VS Code MCP',
]

export const ogImage = {
  url: '/og-image.png',
  width: 1200,
  height: 630,
  alt: 'PlainQuery — ask your database in plain English. No SQL. No queue.',
}

export function absoluteUrl(path = '/') {
  return new URL(path, siteUrl).toString()
}

export const softwareJsonLd = {
  '@context': 'https://schema.org',
  '@type': 'SoftwareApplication',
  name: siteName,
  applicationCategory: 'DeveloperApplication',
  operatingSystem: 'Web, macOS, Windows, Linux',
  url: siteUrl,
  description: siteDescription,
  image: absoluteUrl(ogImage.url),
  offers: {
    '@type': 'Offer',
    price: '0',
    priceCurrency: 'USD',
    description: 'Free hosted beta plan with optional paid upgrades.',
  },
  featureList: [
    'Ask Postgres databases questions in plain English',
    'Connects to MCP clients including ChatGPT, Cursor, VS Code, and Claude Desktop',
    'Schema-aware SQL generation',
    'Read-only SQL validation with row caps and timeouts',
    'Hosted service and open-source self-hosting option',
  ],
  sameAs: ['https://github.com/Jarvis-27/mcp-db-agent'],
}

export const organizationJsonLd = {
  '@context': 'https://schema.org',
  '@type': 'Organization',
  name: siteName,
  url: siteUrl,
  logo: absoluteUrl('/pq-mark.svg'),
  sameAs: ['https://github.com/Jarvis-27/mcp-db-agent'],
}
