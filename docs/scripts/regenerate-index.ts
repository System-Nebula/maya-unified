import { regeneratePluginIndex } from "../quartz/plugins/loader/gitLoader.ts"

await regeneratePluginIndex({ verbose: true })
console.log("Done.")
