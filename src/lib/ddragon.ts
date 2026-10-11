const CDN = 'https://ddragon.leagueoflegends.com/cdn/'

/**
 * Icon URL for a reference row's `image` ("16.19.1/img/tft-champion/<file>.png"). The path
 * carries its own Data Dragon version, so old rows keep working after the CDN moves on.
 */
export function iconUrl(image: string | null | undefined): string | null {
  return image ? `${CDN}${image}` : null
}

export const DDRAGON_ORIGIN = 'https://ddragon.leagueoflegends.com'
