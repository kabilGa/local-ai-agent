// esbuild.js — bundles the extension for VS Code
// Why not tsc alone? esbuild is 10-100x faster and produces a single dist/extension.js
// "vscode" is always external — it's provided by VS Code itself, never bundled.

const esbuild = require('esbuild')

const isWatch = process.argv.includes('--watch')
const isProduction = process.argv.includes('--production')

/** @type {import('esbuild').BuildOptions} */
const options = {
  entryPoints: ['src/extension.ts'],
  bundle: true,
  outfile: 'dist/extension.js',
  // VS Code extensions run on Node.js inside VS Code's extension host process
  platform: 'node',
  // "vscode" is a special module injected by VS Code — never bundle it
  external: ['vscode'],
  format: 'cjs',
  sourcemap: !isProduction,
  minify: isProduction,
  logLevel: 'info',
}

if (isWatch) {
  esbuild.context(options).then(ctx => {
    ctx.watch()
    console.log('[esbuild] Watching for changes...')
  })
} else {
  esbuild.build(options).then(() => {
    console.log('[esbuild] Build complete.')
  }).catch(() => process.exit(1))
}
