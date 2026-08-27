import { build } from "esbuild"
import { cp, mkdir, readFile, rm, writeFile } from "node:fs/promises"
import path from "node:path"

const root = path.resolve(import.meta.dirname, "..")
const targets = ["chromium", "firefox", "chromium-devtools"]
await rm(path.join(root, "dist"), { recursive: true, force: true })

for (const target of targets) {
  const out = path.join(root, "dist", target)
  await mkdir(out, { recursive: true })
  await build({
    entryPoints: {
      background: path.join(root, "src/background.ts"),
      content: path.join(root, "src/content.ts"),
      panel: path.join(root, "src/panel.ts"),
      options: path.join(root, "src/options.ts"),
    },
    outdir: out,
    bundle: true,
    format: "esm",
    target: "es2022",
    define: {
      __MAYA_FIREFOX__: JSON.stringify(target === "firefox"),
      __MAYA_DEVTOOLS__: JSON.stringify(target === "chromium-devtools"),
    },
  })
  const manifest = JSON.parse(await readFile(path.join(root, "manifests", `${target}.json`), "utf8"))
  await writeFile(path.join(out, "manifest.json"), `${JSON.stringify(manifest, null, 2)}\n`)
  await cp(path.join(root, "src/panel.html"), path.join(out, target === "firefox" ? "sidebar.html" : "sidepanel.html"))
  await cp(path.join(root, "src/panel.css"), path.join(out, "panel.css"))
  await cp(path.join(root, "src/options.html"), path.join(out, "options.html"))
  await cp(path.join(root, "src/options.css"), path.join(out, "options.css"))
  await cp(path.join(root, "icons"), path.join(out, "icons"), { recursive: true })
}
