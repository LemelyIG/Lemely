/*
 * The drift gate's scene list. Each area keeps its scenes in its own file and
 * this list concatenates them: the shell plan owns scenes-shell.mjs, the
 * Overview plan adds scenes-home.mjs and appends HOME_SCENES below.
 */
import { NATIVE_SCENES } from "./scenes-native.mjs"
import { SHELL_SCENES } from "./scenes-shell.mjs"

export const WINDOWS = [390, 768, 1024, 1440, 1920]
export const HEIGHT = { 390: 844, 768: 1024, 1024: 768, 1440: 900, 1920: 1080, 412: 915 }
export const THEMES = ["light", "dark"]

export const SCENES = [...SHELL_SCENES, ...NATIVE_SCENES]

const ids = new Set()
for (const scene of SCENES) {
  if (ids.has(scene.id)) throw new Error(`duplicate drift scene id ${scene.id}`)
  ids.add(scene.id)
}
