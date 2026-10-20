const CDN = 'https://ddragon.leagueoflegends.com/cdn/'

/**
 * Icon URL for a reference row's `image`: absolute since the seed writes full URLs (Data Dragon
 * for items and traits, CommunityDragon for champions). A relative path from before that
 * ("16.19.1/img/tft-item/<file>.png") still resolves against the Data Dragon CDN.
 */
export function iconUrl(image: string | null | undefined): string | null {
  if (!image) return null
  return image.startsWith('https://') ? image : `${CDN}${image}`
}

export const DDRAGON_ORIGIN = 'https://ddragon.leagueoflegends.com'
export const CDRAGON_ORIGIN = 'https://raw.communitydragon.org'
