import type { MetadataRoute } from 'next'
import { siteUrl } from '@/lib/seo'

const publicRoutes = ['/', '/pricing', '/support', '/privacy-policy', '/terms-of-service']

export default function sitemap(): MetadataRoute.Sitemap {
  const lastModified = new Date()

  return publicRoutes.map((route) => ({
    url: `${siteUrl}${route === '/' ? '' : route}`,
    lastModified,
    changeFrequency: route === '/' ? 'weekly' : 'monthly',
    priority: route === '/' ? 1 : route === '/pricing' ? 0.8 : 0.5,
  }))
}
