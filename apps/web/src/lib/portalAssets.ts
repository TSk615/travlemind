import brandMark from "@/assets/portal/brand-mark.svg"
import portalWorld from "@/assets/portal/portal-world.webp"
import studioEnvironment from "@/assets/portal/studio-environment.webp"
import forestFlow from "@/assets/portal/forest-flow.webp"
import rainWindow from "@/assets/portal/rain-window.webp"
import forestCabin from "@/assets/portal/forest-cabin.webp"
import mistLake from "@/assets/portal/mist-lake.webp"

// Original AI concept art, not verified photographs of a trip's destination.
export const portalAssets = { brandMark, portalWorld, studioEnvironment, forestFlow }
const tripCovers = [rainWindow, forestCabin, mistLake]

export function getTripCover(id: string): string {
  let hash = 0
  for (const character of id) hash = (hash * 31 + character.charCodeAt(0)) >>> 0
  return tripCovers[hash % tripCovers.length]!
}
